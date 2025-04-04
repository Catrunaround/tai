import logging
import re
import yaml
from pathlib import Path
from typing import List

from dependency_injector import containers, providers
from dependency_injector.wiring import Provide, inject
from nougat import NougatModel
from nougat.postprocessing import markdown_compatible
from nougat.utils.checkpoint import get_checkpoint
from nougat.utils.dataset import LazyDataset
from nougat.utils.device import move_to_device
from torch.utils.data import ConcatDataset, DataLoader
from tqdm import tqdm

from ..config_nougat.nougat_config import NougatConfig

logging.basicConfig(level=logging.INFO)


def create_model(config: NougatConfig) -> NougatModel:
    if config.checkpoint is None or not config.checkpoint.exists():
        config.checkpoint = get_checkpoint(config.checkpoint, model_tag=config.model_tag)

    model = NougatModel.from_pretrained(config.checkpoint)
    model = move_to_device(model, bf16=not config.full_precision, cuda=config.batch_size > 0)
    model.eval()
    print("model loaded")  # debug
    return model


class NougatContainer(containers.DeclarativeContainer):
    model = providers.Singleton(
        create_model,
        config=NougatConfig()
    )


def load_datasets(config: NougatConfig, model: NougatModel) -> List[LazyDataset]:
    datasets = []
    for pdf in config.pdf_paths:
        if not pdf.exists():
            continue
        if config.output_dir:
            out_path = config.output_dir / pdf.with_suffix(".mmd").name
            if out_path.exists() and not config.recompute:
                logging.info(f"Skipping {pdf.name}, already computed. Run with recompute=True to convert again.")
                continue
        try:
            dataset = LazyDataset(
                pdf,
                model.encoder.prepare_input,
                config.pages,
            )
            datasets.append(dataset)
        except Exception as e:
            logging.info(f"Could not load file {str(pdf)}: {e}")
    return datasets


def process_output(output: str, page_num: int, config: NougatConfig) -> str:
    if output.strip() == "[MISSING_PAGE_POST]":
        return f"\n\n[MISSING_PAGE_EMPTY:{page_num}]\n\n"
    if config.markdown_compatible:
        output = markdown_compatible(output)
        output = f"{output.strip()}\n\n"
    return output


@inject
def main(config: NougatConfig, model: NougatModel = Provide[NougatContainer.model]):
    datasets = load_datasets(config, model)

    if not datasets:
        logging.info("No valid datasets found.")
        return

    dataloader = DataLoader(
        ConcatDataset(datasets),
        batch_size=config.batch_size,
        shuffle=False,
        collate_fn=LazyDataset.ignore_none_collate,
    )

    predictions = []
    file_index = 0
    page_num = 0
    current_line = 1  # Line counter for the markdown file
    page_info_list = []  # List to store metadata for each page

    for sample, is_last_page in tqdm(dataloader):
        model_output = model.inference(image_tensors=sample, early_stopping=config.skipping)

        for j, output in enumerate(model_output["predictions"]):
            if page_num == 0:
                logging.info(f"Processing file {datasets[file_index].name} with {datasets[file_index].size} pages")
            page_num += 1

            # Process output and include page number
            processed_output = process_output(output, page_num, config)

            # Calculate the number of lines in the current page
            line_count = processed_output.count('\n')

            # Add page metadata
            page_info_list.append({'page_num': page_num, 'start_line': current_line})
            predictions.append(processed_output)
            current_line += line_count  # Update line counter

            if is_last_page[j]:
                out = "".join(predictions).strip()
                out = re.sub(r"\n{3,}", "\n\n", out).strip()
                if config.output_dir:
                    # Get the original filename
                    original_name = datasets[file_index].name

                    # Construct the output markdown file path
                    out_path = config.output_dir / (Path(original_name).stem + ".mmd")
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text(out, encoding="utf-8")

                    # Construct the metadata file path
                    metadata_path = config.output_dir / (Path(original_name).stem + "_page_info.yaml")
                    with open(metadata_path, 'w', encoding='utf-8') as yaml_file:
                        yaml.dump({'pages': page_info_list}, yaml_file, allow_unicode=True)
                        logging.info(f"Metadata written to {metadata_path}")
                else:
                    print(out, "\n\n")
                    # If not writing to a file, print the metadata as well
                    print(yaml.dump({'pages': page_info_list}, allow_unicode=True))

                # Reset variables for the next file
                predictions = []
                page_num = 0
                current_line = 1
                page_info_list = []
                file_index += 1


def run_nougat(config: NougatConfig):
    """Run Nougat with the provided configuration.
    model is initialized using config only on the first time run_nougat is called .
    """
    if not hasattr(run_nougat, "container"):
        run_nougat.container = NougatContainer()
    run_nougat.container.wire(modules=[__name__])
    main(config)