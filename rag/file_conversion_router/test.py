from pathlib import Path

input_dir = Path("/courses/F1_racing_old/F1_Official")
for html_file in input_dir.rglob("*.html"):
  metadata_file = html_file.parent / f"{html_file.name}_metadata.yaml"
  if not metadata_file.exists():
      print(f"Missing metadata for: {html_file}")
      # You could create a placeholder:
      # with open(metadata_file, "w") as f:
      #     f.write(f"URL: file://{html_file}")
