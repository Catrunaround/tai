import pickle
from pathlib import Path
from rag.file_conversion_router.classes.chunk import Chunk

def load_pkl_file(file_path: Path):
    """Load and return the contents of a pickle file.

    Args:
        file_path (Path): Path to the pickle file.

    Returns:
        The contents of the pickle file.
    """
    with open(file_path, "rb") as file:
        data = pickle.load(file)
    return data

# Specify the path to the .pkl file
file_path = Path("/Users/yyk956614/tai/tests/test_rag/data/unit_tests/pdf/expected_output/61a-sp24-mt1/61a-sp24-mt1.pkl")

# Load the contents of the .pkl file
pkl_contents = load_pkl_file(file_path)

# # Find out how many content chunks there are
num_chunks = len(pkl_contents)

# # Display the number of content chunks
print(f"Number of content chunks: {num_chunks}")
for idx, chunk in enumerate(pkl_contents):
    print(f"Chunk {idx + 1}:")
    print(f"URL: {chunk.chunk_url}")
    print(f"Page number: {chunk.page_num}")
    print("-" * 40)  # Separator for better readability


