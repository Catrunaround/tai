import os
def pdf_to_md(input_path, output_path):
    # Command to execute
    command = f"nougat {input_path} -o {output_path} -m 0.1.0-base --no-skipping"
    # Run the command
    os.system(command)


if __name__ == '__main__':
    pdf_to_md("proj0.pdf", "Discussion")