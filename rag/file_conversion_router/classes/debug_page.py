from pathlib import Path
import yaml
from rag.file_conversion_router.classes.page import Page
from pathlib import Path
import yaml

def process_md_with_two_yaml(md_path: Path, page_num_yaml_path: Path, url_yaml_path: Path, file_type: str = "pdf") -> Page:
    """
    Process an existing markdown file along with two YAML files: 
    one for page numbers and one for URLs, to generate a Page instance.
    
    Args:
        md_path (Path): Path to the markdown file.
        page_num_yaml_path (Path): Path to the YAML metadata file containing page numbers and start lines.
        url_yaml_path (Path): Path to the YAML file containing URLs for each page.
        file_type (str): Type of the file (e.g., 'markdown'). Default is "markdown".
    
    Returns:
        Page: An instance of the Page class with content, page numbers, and URLs loaded.
    """
    # Get the stem (name without extension) of the Markdown file
    stem = md_path.stem
    
    # Read the markdown file content
    try:
        with open(md_path, "r", encoding="utf-8") as input_file:
            content_text = input_file.read()
    except Exception as e:
        print(f"Error reading markdown file: {e}")
        return
    
    # Load the page number metadata from the first YAML file
    if not page_num_yaml_path.exists():
        print(f"Page number YAML file not found at {page_num_yaml_path}")
        return
    try:
        with open(page_num_yaml_path, "r", encoding="utf-8") as f:
            page_num_metadata = yaml.safe_load(f)
    except Exception as e:
        print(f"Error reading page number YAML file: {e}")
        return
    
    print(f"Page Number Metadata: {page_num_metadata}")  # Debugging statement
    
    # Load the URL metadata from the second YAML file
    if not url_yaml_path.exists():
        print(f"URL YAML file not found at {url_yaml_path}")
        return
    try:
        with open(url_yaml_path, "r", encoding="utf-8") as f:
            url_metadata = yaml.safe_load(f)
    except Exception as e:
        print(f"Error reading URL YAML file: {e}")
        return
    
    print(f"URL Metadata: {url_metadata}")  # Debugging statement
    
    # Extract the URL for this page (if available in the metadata)
    url = url_metadata.get("URL", "")

    # Build content dictionary to pass into Page class
    content = {"text": content_text}
    
    # Create and return a Page instance using the existing markdown content and metadata for page numbers and URL
    return Page(pagename=stem, content=content, filetype=file_type, page_url=url, metadata_path=page_num_yaml_path)




md_path = Path("output_tmp/expected_output/filename/filename.md")
page_num_yaml_path = Path("output_tmp/expected_output/filename/filename.yaml")
url_yaml_path = Path("output_tmp/input/filename_metadata.yaml")


page_instance = process_md_with_two_yaml(md_path, page_num_yaml_path, url_yaml_path)

# 如果需要生成 chunks
if page_instance:
    page_instance.to_chunk()
    for idx, chunk in enumerate(page_instance.chunks):
        print(f"Chunk {idx + 1}:")
        print(f"  Page Number: {chunk.page_num}")
        print(f"  URL: {chunk.chunk_url}")
