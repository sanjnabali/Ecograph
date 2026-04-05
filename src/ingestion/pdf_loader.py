import os
import requests
from datasets import load_dataset
from dotenv import load_dotenv

load_dotenv()

def download_esg_reports(limit=5):
    print("Loading HuggingFace 'corpus' subset (test split)...")
    try:
        # Changed split from 'train' to 'test' based on dataset metadata
        ds = load_dataset("vidore/esg_reports_human_labeled_v2", "corpus", split="test")
        
        os.makedirs("data", exist_ok=True)
        
        seen_urls = set()
        downloaded = 0
        
        for row in ds:
            # The dataset uses 'pdf_url' as the column name for the source PDF
            url = row.get('pdf_url')
            company = row.get('company', f"company_{downloaded}")
            
            if url and url not in seen_urls and downloaded < limit:
                print(f"[{downloaded+1}/{limit}] Downloading {company} report...")
                try:
                    # Timeout is important for large ESG PDFs
                    response = requests.get(url, timeout=60) 
                    response.raise_for_status() # Proper error handling for bad links
                    
                    # Sanitize filename (remove spaces/special chars)
                    safe_name = "".join([c if c.isalnum() else "_" for c in company])
                    file_path = f"data/{safe_name}_2024.pdf"
                    
                    with open(file_path, "wb") as f:
                        f.write(response.content)
                    
                    seen_urls.add(url)
                    downloaded += 1
                except Exception as e:
                    print(f"Failed to download {url}: {e}")
                    
        print(f"Successfully downloaded {downloaded} reports to /data folder.")

    except Exception as e:
        print(f"Critical error loading dataset: {e}")

if __name__ == "__main__":
    download_esg_reports()