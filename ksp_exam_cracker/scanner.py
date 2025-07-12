import os
from PIL import Image
import pytesseract
import re

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

def extract_text_from_pics_and_get_score():
    pic_dir = "pics"
    all_texts = []
    print("[debug] Starting OCR on screenshots in 'pics/' folder...")

    for fname in sorted(os.listdir(pic_dir)):
        if fname.lower().endswith(".png"):
            img_path = os.path.join(pic_dir, fname)
            print(f"[debug] OCR processing: {img_path}")
            try:
                img = Image.open(img_path)
                text = pytesseract.image_to_string(img, lang="eng+tha")
                all_texts.append(text)
                print(f"[debug] Extracted text from {fname}: {text[:100]}...")
            except Exception as e:
                print(f"[error] Failed to process {fname}: {e}")

    combined_text = "\n".join(all_texts)
    print("[debug] Finished extracting text from all images.")

    # Use regex to find all scores
    matches = re.findall(r'Score\s+(\d+)/30', combined_text, re.IGNORECASE)
    matches += re.findall(r'(\d+)\s*คะแนน', combined_text)

    if matches:
        last_score = int(matches[-1])
        print(f"[RESULT] ✅ Found last score occurrence directly from OCR: {last_score}/30")
        return last_score
    else:
        print("[error] Could not find any score pattern in OCR text.")
        return None

if __name__ == "__main__":
    score = extract_text_from_pics_and_get_score()
    if score is not None:
        print(f"[RESULT] Final score: {score}/30")
        
        try:
            for fname in os.listdir("pics"):
                if fname.lower().endswith(".png"):
                    os.remove(os.path.join("pics", fname))
            print("[debug] All pics deleted since score was successfully found.")
        except Exception as e:
            print(f"[error] Failed to delete pics: {e}")
    else:
        print("[error] Could not determine the score from the screenshots.")
