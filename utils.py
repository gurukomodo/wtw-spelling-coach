from PIL import Image, ImageOps, ImageEnhance, ImageFilter
import io
import base64
import re

def preprocess_image(uploaded_file):
    img = Image.open(uploaded_file)
    img = ImageOps.exif_transpose(img)
    
    # 1. Grayscale
    img = img.convert("L")
    
    # 2. Sharpen the edges of the handwriting
    img = img.filter(ImageFilter.SHARPEN)
    
    # 3. Aggressive Contrast (Makes the paper white and ink black)
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(3.0) 
    
    # 4. Brightness (Helps if the photo was taken in a dark classroom)
    brightner = ImageEnhance.Brightness(img)
    img = brightner.enhance(1.2)

    buffered = io.BytesIO()
    img.save(buffered, format="JPEG")
    img_str = base64.b64encode(buffered.getvalue()).decode('utf-8')
    
    return img_str, img  # Return both the string for AI and the object for Streamlit

def clean_ai_formatting(text: str) -> str:
    """Strips raw Markdown bold asterisks and converts asterisk bullets to clean bullet symbols."""
    if not text:
        return ""
    # Remove bold asterisks **text** -> text
    cleaned = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    # Replace starting asterisks/dashes with clean bullet points
    cleaned = re.sub(r'^\s*[\*\-]\s+', '• ', cleaned, flags=re.MULTILINE)
    return cleaned.strip()