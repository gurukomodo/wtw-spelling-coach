# assessment_generator.py
import random
import uuid
import qrcode
import os
from datetime import datetime
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from svglib.svglib import svg2rlg
from reportlab.graphics import renderPDF
import constants

# Global Configuration Deployment Pointer
APP_URL = "https://unboxed.streamlit.app"

def cluster_class_for_assessments(student_levels):
    """Sorts class groups into distinct test groups based on roster distance."""
    active_levels = set()
    for lvl in student_levels:
        if isinstance(lvl, str) and lvl.lower().startswith('g'):
            try:
                active_levels.add(int(lvl.lower().replace('g', '')))
            except ValueError:
                pass
    
    sorted_levels = sorted(list(active_levels))
    if not sorted_levels:
        return [[1]]
        
    if (max(sorted_levels) - min(sorted_levels)) <= 3:
        return [sorted_levels]
        
    chunks = []
    for i in range(0, len(sorted_levels), 2):
        chunks.append(sorted_levels[i:i+2])
    return chunks

def generate_class_diagnostics(student_levels, total_words=16):
    """Assembles dynamic test profiles based on current class sub-groups.

    Each generated test targets `total_words` words in total, split as
    evenly as possible across the g-levels included in its cluster (e.g. a
    combined G2-G3 test draws 8 words from each level, not 16 from each).
    """
    clusters = cluster_class_for_assessments(student_levels)
    generated_tests = []
    
    for cluster in clusters:
        test_id = f"DIAG-{str(uuid.uuid4())[:6].upper()}"
        test_words = []
        feature_map = {}

        num_levels = len(cluster)
        base_count = total_words // num_levels
        remainder = total_words % num_levels

        for i, num in enumerate(cluster):
            # Give the first `remainder` levels one extra word so the
            # cluster's total lands on `total_words` even when it doesn't
            # divide evenly (e.g. 16 words / 3 levels = 6, 5, 5).
            words_for_this_level = base_count + (1 if i < remainder else 0)
            target_g = f"g{num}"
            available = [w for w, d in constants.PSI_WORD_BANK.items() if target_g in d["features"]]
            
            random.shuffle(available)
            for word in available[:words_for_this_level]:
                if word not in test_words:
                    test_words.append(word)
                    feature_map[word] = constants.PSI_WORD_BANK[word]["features"]
                    
        min_g, max_g = min(cluster), max(cluster)
        lbl = f"Diagnostic Test G{min_g}-G{max_g}" if min_g != max_g else f"Diagnostic Test G{min_g}"
        
        generated_tests.append({
            "assessment_id": test_id,
            "test_name": lbl,
            "created_at": datetime.now().strftime("%d/%m/%Y %I:%M %p"),
            "words": test_words,
            "feature_map": feature_map
        })
    return generated_tests

def generate_psi_baseline():
    """Generates the comprehensive, structured 26-word baseline assessment."""
    ordered_words = [
        "fan", "pet", "dig", "rob", "hope", "wait", "gum", "sled", "stick", "shine",
        "dream", "blade", "coach", "fright", "chewed", "crawl", "wishes", "thorn",
        "shouted", "spoil", "growl", "third", "camped", "tries", "clapping", "riding"
    ]
    
    return {
        "assessment_id": "DIAG-PSI-BASE",
        "test_name": "Primary Spelling Inventory (Baseline)",
        "created_at": datetime.now().strftime("%d/%m/%Y %I:%M %p"),
        "words": ordered_words,
        "feature_map": {w: constants.PSI_WORD_BANK[w]["features"] for w in ordered_words}
    }

def generate_qr_image(data_str):
    qr = qrcode.QRCode(version=1, box_size=10, border=1)
    qr.add_data(data_str)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#006633", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)

def draw_page_decorations(c, w, h, test_data, is_teacher, page_num):
    """Draws premium minimal branding headers, 50% larger vector SVG logos, and clean routing anchors."""
    primary_color = colors.HexColor("#006633")    # Rich Forest Green
    neutral_dark = colors.HexColor("#222222")     # Charcoal text
    
    # 1. Top Decorative Layout Band
    c.setFillColor(primary_color)
    c.rect(0, h - 12, w, 12, fill=True, stroke=False)
    
    # 2. Native Vector SVG Branding Logo Integration (50% Larger Layout Scale Window)
    logo_path = "logo.svg"
    logo_drawn = False
    if os.path.exists(logo_path):
        try:
            drawing = svg2rlg(logo_path)
            # Increased target drawing bounds matrix from 28.0pt to 42.0pt (50% larger asset)
            factor = 42.0 / drawing.height
            drawing.width *= factor
            drawing.height *= factor
            drawing.scale(factor, factor)
            renderPDF.draw(drawing, c, 40, h - 62)
            logo_drawn = True
        except:
            pass
                
    if not logo_drawn:
        # Typographic fallback layout matched to the expanded 50% design scale bounds
        c.setFillColor(primary_color)
        c.roundRect(40, h - 56, 36, 36, 6, fill=True, stroke=False)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 20)
        c.drawString(50, h - 46, "U")
        c.setFillColor(primary_color)
        c.setFont("Helvetica-Bold", 22)
        c.drawString(84, h - 47, "Unboxed")
        
    # 3. Dynamic QR Web Routing Link (Combines Variable Base App URL + Diagnostic Context)
    routing_url = f"{APP_URL}/?assessment_id={test_data['assessment_id']}"
    qr_img = generate_qr_image(routing_url)
    c.drawImage(qr_img, w - 100, h - 102, width=60, height=60)
    
    c.setFillColor(primary_color)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(w - 70, h - 112, test_data['assessment_id'])

    # 4. Content Structural Segments
    if is_teacher:
        c.setStrokeColor(colors.HexColor("#e5e7eb"))
        c.setLineWidth(1)
        c.line(40, h - 74, w - 40, h - 74)
        
        c.setFillColor(neutral_dark)
        c.setFont("Helvetica-Bold", 13)
        c.drawString(40, h - 96, test_data['test_name'])
        c.setFont("Helvetica-Bold", 11)
        c.drawRightString(w - 115, h - 44, "Teacher Guide")
        # CLEANUP: Heavy generated time and subpage tracks are fully extracted to maintain clean viewports
    else:
        # Student configuration minimal view header space
        if page_num == 1:
            c.setFont("Helvetica-Bold", 12)
            c.setFillColor(neutral_dark)
            c.drawString(40, h - 95, "Name: _____________________________________")
            c.drawString(340, h - 95, "Date: _______________")

def draw_primary_school_lines(c, x_start, y_baseline, width=225, row_height=16):
    """Draws a spacious primary school triplet rule frame scaled to 2x (16pt per zone)."""
    c.saveState()
    
    # 1. Solid Primary Baseline
    c.setStrokeColor(colors.HexColor("#777777"))
    c.setLineWidth(0.75)
    c.setDash() 
    c.line(x_start, y_baseline, x_start + width, y_baseline)
    
    # 2. Dashed Mid-Height Guidance Line (16pt up)
    c.setStrokeColor(colors.HexColor("#bbaaaa"))  
    c.setLineWidth(0.5)
    c.setDash(2.5, 2.5) 
    c.line(x_start, y_baseline + row_height, x_start + width, y_baseline + row_height)
    
    # 3. Solid Top Boundary Cap Line (32pt up)
    c.setStrokeColor(colors.HexColor("#cccccc"))
    c.setLineWidth(0.5)
    c.setDash() 
    c.line(x_start, y_baseline + (row_height * 2), x_start + width, y_baseline + (row_height * 2))
    
    c.restoreState()

def draw_page_footer(c, w, assessment_id, page_num):
    """Draws sleek footer architectures prioritizing active digital reference links over static metadata names."""
    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(colors.HexColor("#006633"))
    # CLEANUP: Swapped company string to lean completely on the uppercase target routing app URL
    c.drawCentredString(w / 2.0, 22, f"{APP_URL.upper()}  •  DOCUMENT ID: {assessment_id}  •  PAGE {page_num}")

def draw_practice_card(c, x, y, width, height, student_data, card_num):
    """Draws a single practice list card with dashed cutting border."""
    primary_color = colors.HexColor("#006633")
    neutral_dark = colors.HexColor("#222222")
    
    # Draw dashed border for cutting
    c.setStrokeColor(colors.HexColor("#999999"))
    c.setLineWidth(0.5)
    c.setDash(3, 3)
    c.roundRect(x, y, width, height, 4, stroke=1, fill=0)
    c.setDash()  # Reset to solid
    
    # Card header background
    c.setFillColor(primary_color)
    c.rect(x, y + height - 25, width, 25, fill=True, stroke=False)
    
    # Student name and date
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x + 5, y + height - 18, student_data['student_name'])
    c.setFont("Helvetica", 8)
    c.drawRightString(x + width - 5, y + height - 18, datetime.now().strftime("%Y-%m-%d"))
    
    # Group focus
    c.setFillColor(neutral_dark)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x + 5, y + height - 40, f"Group: {student_data['group_title'].upper()}")
    
    # List title
    c.setFont("Helvetica-Oblique", 9)
    c.setFillColor(colors.HexColor("#444444"))
    c.drawString(x + 5, y + height - 52, student_data['list_title'])
    
    # Word list
    c.setFont("Helvetica", 9)
    c.setFillColor(neutral_dark)
    word_y = y + height - 70
    for idx, word in enumerate(student_data['words'], 1):
        if word_y < y + 10:
            break  # Don't overflow card
        c.drawString(x + 5, word_y, f"{idx}. {word}")
        word_y -= 14

def render_batch_practice_lists_pdf(student_practice_batch):
    """
    Generates a multi-slip PDF with practice lists for multiple students.
    
    Args:
        student_practice_batch: List of dicts containing:
            - student_name: str
            - list_title: str
            - group_title: str
            - words: list of str
    
    Returns:
        BytesIO buffer containing the PDF
    """
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    w, h = A4
    
    # Grid configuration: 2 columns x 3 rows = 6 cards per page
    cols = 2
    rows = 3
    card_width = (w - 60) / cols  # 30pt margin on each side
    card_height = (h - 80) / rows  # 40pt margin top/bottom
    margin_x = 30
    margin_y = 40
    
    page_num = 1
    card_idx = 0
    
    for student_data in student_practice_batch:
        # Calculate card position
        col = card_idx % cols
        row = card_idx // cols
        
        x = margin_x + (col * card_width)
        y = margin_y + ((rows - 1 - row) * card_height)
        
        draw_practice_card(c, x, y, card_width - 10, card_height - 10, student_data, card_idx + 1)
        
        card_idx += 1
        
        # Start new page if we've filled the grid
        if card_idx >= cols * rows:
            draw_page_footer(c, w, "BATCH-PRACTICE", page_num)
            c.showPage()
            page_num += 1
            card_idx = 0
    
    # Draw footer on last page if there are cards
    if card_idx > 0 or not student_practice_batch:
        draw_page_footer(c, w, "BATCH-PRACTICE", page_num)
    
    c.save()
    buffer.seek(0)
    return buffer

def render_assessment_pdf(test_data, is_teacher=True, use_primary_lines=True):
    """Generates continuous stream single or dual column layout templates with clean structural lines."""
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    w, h = A4
    
    page_num = 1
    draw_page_decorations(c, w, h, test_data, is_teacher, page_num)
    
    if is_teacher:
        y = h - 132
        line_spacing = 25
        
        for idx, word in enumerate(test_data['words'], 1):
            if y < 60:
                draw_page_footer(c, w, test_data['assessment_id'], page_num)
                c.showPage()
                page_num += 1
                draw_page_decorations(c, w, h, test_data, is_teacher, page_num)
                y = h - 132
                
            c.setFillColor(colors.HexColor("#222222"))
            c.setFont("Helvetica-Bold", 11)
            c.drawString(40, y, f"{idx}.")
            c.drawString(65, y, word.upper())
            
            c.setFont("Helvetica-Oblique", 11)
            c.setFillColor(colors.HexColor("#444444"))
            sentence = constants.PSI_WORD_BANK.get(word, {}).get("sentence", "")
            c.drawString(145, y, f'"{sentence}"')
            y -= line_spacing
    else:
        # Student Layout Geometry Configuration (2 Columns, Clean Compact Setup)
        words = test_data['words']
        midpoint = (len(words) + 1) // 2
        
        col1_x = 40
        col2_x = 315
        line_width = 240
        
        start_y = h - 155
        line_spacing = 50  
        
        for idx, word in enumerate(words, 1):
            if idx <= midpoint:
                col_x = col1_x
                row_idx = idx - 1
            else:
                col_x = col2_x
                row_idx = idx - midpoint - 1
                
            y = start_y - (row_idx * line_spacing)
            
            if y < 65:
                draw_page_footer(c, w, test_data['assessment_id'], page_num)
                c.showPage()
                page_num += 1
                draw_page_decorations(c, w, h, test_data, is_teacher, page_num)
                start_y = h - 110  
                y = start_y - (row_idx * line_spacing)
            
            c.setFillColor(colors.HexColor("#222222"))
            c.setFont("Helvetica-Bold", 11)
            c.drawString(col_x, y + 10, f"{idx}.")
            
            if use_primary_lines:
                draw_primary_school_lines(c, col_x + 22, y, width=line_width, row_height=16)
            else:
                c.setStrokeColor(colors.HexColor("#999999"))
                c.setLineWidth(0.75)
                c.line(col_x + 22, y, col_x + 22 + line_width, y)
                
    draw_page_footer(c, w, test_data['assessment_id'], page_num)
    c.save()
    buffer.seek(0)
    return buffer