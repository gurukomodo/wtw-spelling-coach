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
        elements.append(self.make