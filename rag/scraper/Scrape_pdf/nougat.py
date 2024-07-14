import os
def pdf_to_md(pdf_file_path, folder_name):
    # Command to execute
    command = f"nougat {pdf_file_path} -o {folder_name} -m 0.1.0-base --no-skipping"
    # Run the command
    os.system(command)


if __name__ == '__main__':
    pdf_to_md("rag\scraper\Scrape_pdf\example.pdf", "rag\scraper\Scrape_pdf")