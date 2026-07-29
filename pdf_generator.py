# pdf_generator.py
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, black
from reportlab.lib.utils import ImageReader
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.platypus.flowables import Flowable, PageBreak
from io import BytesIO
from svglib.svglib import svg2rlg
import qrcode
import os
from reportlab.graphics import renderPDF

class HeaderWithLine(Flowable):
    """Polished flowable for section headers with clean structural dividers"""
    def __init__(self, text, style):
        Flowable.__init__(self)
        self.text = text
        self.style = style
        
    def wrap(self, availWidth, availHeight):
        return availWidth, self.style.leading + 14
    
    def draw(self):
        self.canv.saveState()
        
        # Draw the header text
        self.canv.setFont(self.style.fontName, self.style.fontSize)
        self.canv.setFillColor(self.style.textColor)
        
        text_width = self.canv.stringWidth(self.text, self.style.fontName, self.style.fontSize)
        # Elegant left alignment with matching structural rule
        x = 0 
        y = self.height - self.style.leading
        
        self.canv.drawString(x, y, self.text)
        
        # Modern thin accent underline rule
        line_y = y - 8
        self.canv.setStrokeColor(HexColor('#006633'))  # Deep Forest Green
        self.canv.setLineWidth(1.5)
        self.canv.line(0, line_y, self.canv._pagesize[0] - 80, line_y)
        
        self.canv.restoreState()

class PrimaryLinesFlowable(Flowable):
    """Renders high-precision primary handwriting guidelines inside the document layout stream"""
    def __init__(self, width, height=24, row_height=7):
        Flowable.__init__(self)
        self.width = width
        self.height = height
        self.row_height = row_height
        
    def wrap(self, availWidth, availHeight):
        return self.width, self.height
        
    def draw(self):
        self.canv.saveState()
        y_baseline = 4
        
        # 1. Solid Gray Baseline
        self.canv.setStrokeColor(HexColor('#888888'))
        self.canv.setLineWidth(0.75)
        self.canv.setDash()
        self.canv.line(0, y_baseline, self.width, y_baseline)
        
        # 2. Dashed Mid-height Guidance Boundary
        self.canv.setStrokeColor(HexColor('#bbbbbb'))
        self.canv.setLineWidth(0.5)
        self.canv.setDash(2, 2)
        self.canv.line(0, y_baseline + self.row_height, self.width, y_baseline + self.row_height)
        
        # 3. Solid Top Cap Boundary
        self.canv.setStrokeColor(HexColor('#dcdcdc'))
        self.canv.setLineWidth(0.5)
        self.canv.setDash()
        self.canv.line(0, y_baseline + (self.row_height * 2), self.width, y_baseline + (self.row_height * 2))
        
        self.canv.restoreState()

class ActivityPDF:
    def __init__(self, data):
        self.data = data
        self.styles = getSampleStyleSheet()
        
        # Configure Premium Custom Design Styles
        self.styles.add(ParagraphStyle(
            name='header',
            fontSize=18,
            leading=22,
            fontName='Helvetica-Bold',
            textColor=HexColor('#006633'),
            spaceAfter=10
        ))
        
        self.styles.add(ParagraphStyle(
            name='callout_title',
            fontSize=11,
            leading=14,
            fontName='Helvetica-Bold',
            textColor=HexColor('#004d26'),
        ))
        
        self.styles.add(ParagraphStyle(
            name='callout_body',
            fontSize=10.5,
            leading=14,
            fontName='Helvetica',
            textColor=HexColor('#222222'),
        ))
        
        self.styles.add(ParagraphStyle(
            name='body',
            parent=self.styles['Normal'],
            fontSize=11,
            leading=16,
            fontName='Helvetica',
            textColor=HexColor('#333333')
        ))

    def make_educational_callout(self, label, text):
        """Wraps standard text frameworks into beautiful left-bordered content cards"""
        content = f"<b>{label}</b><br/>{text}"
        p = Paragraph(content, self.styles['callout_body'])
        
        card_table = Table([[p]], colWidths=[A4[0] - 80])
        card_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), HexColor('#f4f9f5')),
            ('LINELEFT', (0, 0), (0, 0), 4, HexColor('#006633')),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('LEFTPADDING', (0, 0), (-1, -1), 14),
            ('RIGHTPADDING', (0, 0), (-1, -1), 14),
        ]))
        return card_table

    def draw_header_footer(self, canvas, doc):
        """Draws systemic branding anchors, vector logos, and tracking targets cleanly"""
        canvas.saveState()
        w, h = A4
        
        logo_path = getattr(doc, 'logo_path', None)
        qr_url = getattr(doc, 'qr_url', None)
        
        # 1. Top Decorative Layout Band
        canvas.setFillColor(HexColor('#006633'))
        canvas.rect(0, h - 12, w, 12, fill=1, stroke=0)
        
        # 2. Render Scaled Vector Branding Logo
        if logo_path and os.path.exists(logo_path):
            try:
                drawing = svg2rlg(logo_path)
                scaling_factor = 0.45
                drawing.width *= scaling_factor
                drawing.height *= scaling_factor
                drawing.scale(scaling_factor, scaling_factor)
                renderPDF.draw(drawing, canvas, w - 110, h - 55)
            except Exception as e:
                # Elegant typographic fallback in case of vector subsystem fault
                canvas.setFillColor(HexColor('#006633'))
                canvas.setFont("Helvetica-Bold", 14)
                canvas.drawRightString(w - 40, h - 45, "Unboxed")
        else:
            canvas.setFillColor(HexColor('#006633'))
            canvas.setFont("Helvetica-Bold", 14)
            canvas.drawRightString(w - 40, h - 45, "Unboxed")
            
        # 3. Footer Attribution & QR Digital-Link Core
        canvas.setStrokeColor(HexColor('#e0e0e0'))
        canvas.setLineWidth(0.5)
        canvas.line(40, 45, w - 40, 45)
        
        canvas.setFillColor(HexColor('#777777'))
        canvas.setFont("Helvetica", 8)
        canvas.drawString(40, 32, "UNBOXED LEARNING PLATFORM  •  PERSONALIZED PRACTICE MODULE")
        
        if qr_url:
            try:
                qr = qrcode.QRCode(version=1, box_size=10, border=1)
                qr.add_data(qr_url)
                qr.make(fit=True)
                img = qr.make_image(fill_color="#006633", back_color="white")
                
                buffer = BytesIO()
                img.save(buffer, format='PNG')
                buffer.seek(0)
                
                canvas.drawImage(ImageReader(buffer), w - 85, 12, width=45, height=45)
            except:
                pass
        
        canvas.restoreState()

    def generate_pdf(self):
        buffer = BytesIO()
        current_dir = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.join(current_dir, "logo.svg")
        
        qr_url = f"https://unboxed-learning.streamlit.app/?student_id={self.data['student_id']}&task={self.data['task_id']}"
        
        # Build document template margins to maximize area usage safely
        doc = SimpleDocTemplate(
            buffer, 
            pagesize=A4,
            leftMargin=40,
            rightMargin=40,
            topMargin=60,
            bottomMargin=65
        )
        
        doc.logo_path = logo_path
        doc.qr_url = qr_url
        
        elements = []

        # Track Component Assembler Loops
        elements.extend(self.create_teacher_guide())
        elements.append(PageBreak())

        elements.extend(self.create_task_sheet())
        elements.append(PageBreak())

        elements.extend(self.create_response_sheet())

        doc.build(elements, onFirstPage=self.draw_header_footer, onLaterPages=self.draw_header_footer)
        return buffer

    def create_teacher_guide(self):
        elements = []
        elements.append(HeaderWithLine("TEACHER INSTRUCTIONAL GUIDE", self.styles['header']))
        elements.append(Spacer(1, 15))
        
        # Wrap foundational markers inside high-visibility callouts
        elements.append(self.make_educational_callout("WALT (We Are Learning To)", self.data['walt_text']))
        elements.append(Spacer(1, 10))
        elements.append(self.make_educational_callout("WILF (What I'm Looking For)", self.data['wilf_text']))
        elements.append(Spacer(1, 10))
        elements.append(self.make_educational_callout("TIB (This Is Because)", self.data['tib_text']))
        elements.append(Spacer(1, 20))

        if self.data.get('teacher_notes'):
            elements.append(Paragraph("Teacher Notes", self.styles['callout_title']))
            elements.append(Spacer(1, 4))
            elements.append(Paragraph(self.data['teacher_notes'], self.styles['body']))
            elements.append(Spacer(1, 20))

        elements.append(Paragraph("Word List", self.styles['callout_title']))
        elements.append(Spacer(1, 6))

        words = self.data.get('content_data', [])
        word_rows = [", ".join(words[i:i + 5]) for i in range(0, len(words), 5)]
        for row in word_rows:
            elements.append(Paragraph(row, self.styles['body']))

        return elements

    def create_task_sheet(self):
        """Student-facing sheet: read each word, then use it in an original sentence."""
        elements = []
        elements.append(HeaderWithLine("STUDENT TASK SHEET", self.styles['header']))
        elements.append(Spacer(1, 15))

        elements.append(Paragraph(
            "Read each word carefully. Then write your own sentence using the word.",
            self.styles['body']
        ))
        elements.append(Spacer(1, 20))

        words = self.data.get('content_data', [])
        table_data = []
        for word in words:
            table_data.append([Paragraph(f"<b>{word}</b>", self.styles['body']), ""])

        task_table = Table(table_data, colWidths=[100, A4[0] - 220])
        task_table.setStyle(TableStyle([
            ('LINEBELOW', (1, 0), (1, -1), 0.75, HexColor('#888888')),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ]))
        elements.append(task_table)

        return elements

    def create_response_sheet(self):
        """Student practice sheet: primary handwriting lines for each target word."""
        elements = []
        elements.append(HeaderWithLine("SPELLING PRACTICE SHEET", self.styles['header']))
        elements.append(Spacer(1, 15))

        elements.append(Paragraph(
            "Write each word three times on the lines below.",
            self.styles['body']
        ))
        elements.append(Spacer(1, 15))

        words = self.data.get('content_data', [])
        line_width = A4[0] - 120

        for word in words:
            elements.append(Paragraph(f"<b>{word}</b>", self.styles['callout_title']))
            elements.append(Spacer(1, 4))
            for _ in range(3):
                elements.append(PrimaryLinesFlowable(width=line_width))
                elements.append(Spacer(1, 4))
            elements.append(Spacer(1, 10))

        return elements


def generate_class_practice_sheet(class_data, lists_per_page=6):
    """Compact printable sheet of several students' weekly practice lists.

    class_data: list of dicts, each shaped like:
        {'student_name': str, 'group_title': str, 'words': list[str]}
        (group_title and words are typically what's already stored in
        st.session_state[f'practice_list_{student_id}'].)
    lists_per_page: 4 or 6 recommended. 6 uses a 2x3 grid, anything <=4
        uses a 2x2 grid.
    """
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    w, h = A4

    cols = 2
    rows = 3 if lists_per_page > 4 else 2

    margin = 30
    top_margin = 50
    bottom_margin = 40
    gap = 14

    grid_w = w - 2 * margin
    grid_h = h - top_margin - bottom_margin

    card_w = (grid_w - (cols - 1) * gap) / cols
    card_h = (grid_h - (rows - 1) * gap) / rows

    forest = HexColor('#006633')
    dark = HexColor('#222222')
    muted = HexColor('#777777')
    header_bg = HexColor('#f4f9f5')
    border = HexColor('#dddddd')

    def draw_page_header(page_num):
        c.setFillColor(forest)
        c.rect(0, h - 10, w, 10, fill=1, stroke=0)
        c.setFont("Helvetica-Bold", 12)
        c.setFillColor(forest)
        c.drawString(margin, h - 30, "Weekly Practice Lists")
        c.setFont("Helvetica", 8)
        c.setFillColor(muted)
        c.drawRightString(w - margin, h - 30, f"Page {page_num}")

    def draw_card(x, y, student):
        c.setStrokeColor(border)
        c.setLineWidth(0.75)
        c.roundRect(x, y, card_w, card_h, 6, fill=0, stroke=1)

        c.setFillColor(header_bg)
        c.roundRect(x, y + card_h - 26, card_w, 26, 6, fill=1, stroke=0)
        c.rect(x, y + card_h - 26, card_w, 13, fill=1, stroke=0)

        c.setFillColor(dark)
        c.setFont("Helvetica-Bold", 10.5)
        c.drawString(x + 10, y + card_h - 17, student.get('student_name', ''))

        c.setFillColor(muted)
        c.setFont("Helvetica", 8)
        c.drawRightString(x + card_w - 10, y + card_h - 17, student.get('group_title', ''))

        words = student.get('words', [])
        half = (len(words) + 1) // 2
        col1_words, col2_words = words[:half], words[half:]

        line_h = 13.5
        text_top = y + card_h - 40
        col1_x = x + 12
        col2_x = x + card_w / 2 + 4

        c.setFont("Helvetica", 9)
        for i, word in enumerate(col1_words):
            yy = text_top - i * line_h
            c.setFillColor(muted)
            c.drawString(col1_x, yy, f"{i + 1}.")
            c.setFillColor(dark)
            c.drawString(col1_x + 14, yy, word)

        for i, word in enumerate(col2_words):
            yy = text_top - i * line_h
            c.setFillColor(muted)
            c.drawString(col2_x, yy, f"{half + i + 1}.")
            c.setFillColor(dark)
            c.drawString(col2_x + 14, yy, word)

    page_num = 1
    draw_page_header(page_num)

    per_page = cols * rows
    slot = 0
    for student in class_data:
        if slot == per_page:
            c.showPage()
            page_num += 1
            draw_page_header(page_num)
            slot = 0

        row = slot // cols
        col = slot % cols
        x = margin + col * (card_w + gap)
        y = h - top_margin - (row + 1) * card_h - row * gap

        draw_card(x, y, student)
        slot += 1

    c.save()
    buffer.seek(0)
    return buffer


def render_batch_practice_lists_pdf(class_data, lists_per_page=4):
    """
    Printable batch practice sheet — 6 cards per page (3x2) layout.
    Each card: green header band with logo, student name large, date.
    No titles of any kind (no group title, no list title) — just the header and words.
    Words in a single centred column, as large as they can be while fitting all words in the card.

    class_data: list of dicts with keys:
        student_name, words, group_title (optional), list_title (optional)
    lists_per_page: kept in signature for compatibility, but layout is 3x2.
    """
    from datetime import date as _date
    import os as _os

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    w, h = A4

    cols = 3
    rows = 2

    margin = 24
    top_margin = 28
    bottom_margin = 28
    gap = 12

    grid_w = w - 2 * margin
    grid_h = h - top_margin - bottom_margin
    card_w = (grid_w - (cols - 1) * gap) / cols
    card_h = (grid_h - (rows - 1) * gap) / rows

    forest    = HexColor('#006633')
    white     = HexColor('#ffffff')
    dark      = HexColor('#1a1a1a')
    num_color = HexColor('#888888')
    border    = HexColor('#cccccc')

    header_h = 40    # green band height

    # --- resolve logo once ---
    logo_drawing = None
    logo_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "logo.svg")
    if not _os.path.exists(logo_path):
        logo_path = "logo.svg"
    if _os.path.exists(logo_path):
        try:
            from svglib.svglib import svg2rlg
            from reportlab.graphics import renderPDF as _renderPDF
            logo_drawing = svg2rlg(logo_path)
        except Exception:
            logo_drawing = None

    today_str = _date.today().strftime("%d %b %Y")

    def draw_card(x, y, student):
        name  = student.get('student_name', '')
        words = student.get('words', [])

        # --- outer border ---
        c.setStrokeColor(border)
        c.setLineWidth(0.75)
        c.roundRect(x, y, card_w, card_h, 8, fill=0, stroke=1)

        # --- green header band ---
        c.setFillColor(forest)
        # top rounded corners only: draw rect + mask bottom corners
        c.roundRect(x, y + card_h - header_h, card_w, header_h, 8, fill=1, stroke=0)
        c.rect(x, y + card_h - header_h, card_w, 8, fill=1, stroke=0)  # flatten bottom corners

        # --- logo in header (left side) ---
        logo_size = 24
        logo_x = x + 8
        logo_y = y + card_h - header_h + (header_h - logo_size) / 2
        if logo_drawing:
            try:
                from reportlab.graphics import renderPDF as _renderPDF
                factor = logo_size / max(logo_drawing.width, logo_drawing.height)
                logo_drawing.width  *= factor
                logo_drawing.height *= factor
                logo_drawing.scale(factor, factor)
                _renderPDF.draw(logo_drawing, c, logo_x, logo_y)
                # reset scale for next card
                logo_drawing.width  /= factor
                logo_drawing.height /= factor
                logo_drawing.scale(1 / factor, 1 / factor)
            except Exception:
                logo_drawing_fallback(c, logo_x, logo_y, logo_size)
        else:
            logo_drawing_fallback(c, logo_x, logo_y, logo_size)

        # --- student name (large, white) ---
        name_x = x + logo_size + 14
        name_y = y + card_h - header_h + header_h * 0.38
        c.setFillColor(white)
        c.setFont("Helvetica-Bold", 12)
        # truncate name if card is narrow
        max_name_w = card_w - logo_size - 65
        while c.stringWidth(name, "Helvetica-Bold", 12) > max_name_w and len(name) > 4:
            name = name[:-1]
        c.drawString(name_x, name_y, name)

        # --- date (small, white, right-aligned) ---
        c.setFont("Helvetica", 7.5)
        c.setFillColor(HexColor('#ccffcc'))
        c.drawRightString(x + card_w - 8, name_y + 1, today_str)

        # --- word list: single centred block ---
        if not words:
            return

        body_h  = card_h - header_h        # white area height
        padding = 20                       # top + bottom internal padding in body
        available = body_h - padding
        line_h = available / max(len(words), 1)
        word_font_size = min(18, max(10, line_h * 0.55))
        num_font_size  = max(8, word_font_size * 0.7)

        block_h = len(words) * line_h       # total height of word list
        # vertically centre the block in the white area
        block_top = y + body_h - (body_h - block_h) / 2 - line_h * 0.15

        # measure widest word to horizontally centre the block
        num_w = c.stringWidth("10. ", "Helvetica", num_font_size)
        max_word_w = max(
            c.stringWidth(wd, "Helvetica-Bold", word_font_size) for wd in words
        )
        block_w = num_w + max_word_w
        block_x = x + (card_w - block_w) / 2   # left edge of centred block

        for i, word in enumerate(words):
            yy = block_top - i * line_h
            c.setFillColor(num_color)
            c.setFont("Helvetica", num_font_size)
            c.drawRightString(block_x + num_w, yy, f"{i + 1}.")
            c.setFillColor(dark)
            c.setFont("Helvetica-Bold", word_font_size)
            c.drawString(block_x + num_w + 4, yy, word)

    def logo_drawing_fallback(c, lx, ly, sz):
        """Green rounded square with white U — matches draw_page_decorations fallback."""
        c.setFillColor(white)
        c.roundRect(lx, ly, sz, sz, 4, fill=1, stroke=0)
        c.setFillColor(forest)
        c.setFont("Helvetica-Bold", int(sz * 0.6))
        c.drawCentredString(lx + sz / 2, ly + sz * 0.2, "U")

    per_page = cols * rows
    slot = 0
    for student in class_data:
        if slot > 0 and slot % per_page == 0:
            c.showPage()
        row = slot % per_page // cols
        col = slot % per_page % cols
        x = margin + col * (card_w + gap)
        y = h - top_margin - (row + 1) * card_h - row * gap
        draw_card(x, y, student)
        slot += 1

    c.save()
    buffer.seek(0)
    return buffer
