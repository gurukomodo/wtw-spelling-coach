from PIL import Image, ImageOps, ImageEnhance
import io
import base64

def preprocess_image(uploaded_file):
    """
    Cleans the photo: fixes rotation, converts to grayscale, 
    and boosts contrast so ink stands out from paper.
    """
    img = Image.open(uploaded_file)
    
    # 1. Fix phone rotation (EXIF data)
    img = ImageOps.exif_transpose(img)
    
    # 2. Convert to Grayscale
    img = img.convert("L")
    
    # 3. Boost Contrast (2.5x makes faint pencil look like dark ink)
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(2.5) 
    
    # 4. Convert to Base64 for the AI
    buffered = io.BytesIO()
    img.save(buffered, format="JPEG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8')