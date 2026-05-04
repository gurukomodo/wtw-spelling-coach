from reportlab.lib.pagesizes import letter, A4
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, black
from reportlab.lib.utils import ImageReader
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.platypus.flowables import Flowable, PageBreak
from io import BytesIO
from svglib.svglib import svg2rlg
import qrcode
import os
from reportlab.graphics import renderPDF, renderPM


class HeaderWithLine(Flowable):
    """Flowable for headers with horizontal lines"""
    def __init__(self, text, style):
        Flowable.__init__(self)
        self.text = text
        self.style = style
        
    def wrap(self, availWidth, availHeight):
        return availWidth, self.style.leading + 10
    
    def draw(self):
        self.canv.saveState()
        
        # Draw the header text
        self.canv.setFont(self.style.fontName, self.style.fontSize)
        self.canv.setFillColor(self.style.textColor)
        
        # Center the text
        text_width = self.canv.stringWidth(self.text, self.style.fontName, self.style.fontSize)
        x = (self.canv._pagesize[0] - text_width) / 2
        y = self.height - self.style.leading
        
        self.canv.drawString(x, y, self.text)
        
        # Draw horizontal line under the header
        line_y = y - 5
        self.canv.setStrokeColor(HexColor('#006633'))  # Deep Green
        self.canv.setLineWidth(2)
        self.canv.line(50, line_y, self.canv._pagesize[0] - 50, line_y)
        
        self.canv.restoreState()

class ActivityPDF:
    def __init__(self, data):
        self.data = data
        self.styles = getSampleStyleSheet()
        
        # Path verification
        current_dir = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.join(current_dir, "logo.svg")
        print(f"Loading logo from: {logo_path}")
        
        # Add custom styles
        self.styles.add(ParagraphStyle(
            name='header',
            parent=self.styles['Heading1'],
            fontSize=20,
            leading=24,
            alignment=1,
            fontName='Helvetica-Bold',
            textColor=HexColor('#006633')  # Deep Green
        ))
        
        self.styles.add(ParagraphStyle(
            name='section_header',
            parent=self.styles['Heading2'],
            fontSize=14,
            leading=18,
            fontName='Helvetica-Bold',
            textColor=HexColor('#007d70'),
            spaceAfter=6
        ))
        
        self.styles.add(ParagraphStyle(
            name='body',
            parent=self.styles['Normal'],
            fontSize=12,
            leading=16,
            fontName='Helvetica'
        ))

    def draw_header_footer(self, canvas, doc):
        """Draw header and footer on each page"""
        canvas.saveState()
        
        # Get paths and URL from doc
        logo_path = getattr(doc, 'logo_path', None)
        qr_url = getattr(doc, 'qr_url', None)
        
        # Draw logo at specific coordinates (500, 780) - top right
        if logo_path and os.path.exists(logo_path):
            try:
                drawing = svg2rlg(logo_path)
                
                # Scale the logo to fit
                scaling_factor = 0.5
                drawing.width *= scaling_factor
                drawing.height *= scaling_factor
                drawing.scale(scaling_factor, scaling_factor)
                
                # Draw directly to canvas
                renderPDF.draw(drawing, canvas, 500, 780)
            except Exception as e:
                print(f"Error drawing logo: {e}")
                # Debug: draw bright red square if drawing fails
                canvas.setFillColor(HexColor('#FF0000'))  # Bright Red
                canvas.rect(500, 780, 60, 60, fill=1, stroke=0)
        else:
            # Debug: draw bright red square if path doesn't exist
            canvas.setFillColor(HexColor('#FF0000'))  # Bright Red
            canvas.rect(500, 780, 60, 60, fill=1, stroke=0)
        
        # Draw QR code in bottom-right corner
        if qr_url:
            try:
                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_L,
                    box_size=4,
                    border=2,
                )
                qr.add_data(qr_url)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                
                buffer = BytesIO()
                img.save(buffer, format='PNG')
                buffer.seek(0)
                
                img_reader = ImageReader(buffer)
                canvas.drawImage(img_reader, 500, 50, width=60, height=60)
            except:
                pass  # Fallback if QR fails
        
        canvas.restoreState()

    def generate_pdf(self):
        buffer = BytesIO()
        
        # Get the current file's directory for logo path
        current_dir = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.join(current_dir, "logo.svg")
        
        # QR code URL
        qr_url = f"https://unboxed-learning.streamlit.app/?student_id={self.data['student_id']}&task={self.data['task_id']}"
        
        # Create simple doc with A4 size
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        
        # Store logo_path and qr_url in doc for the callback function
        doc.logo_path = logo_path
        doc.qr_url = qr_url
        
        elements = []

        # Page 1: Teacher's Guide
        elements.extend(self.create_teacher_guide())
        elements.append(PageBreak())

        # Page 2: Student Task
        elements.extend(self.create_task_sheet())
        elements.append(PageBreak())

        # Page 3: Response Sheet
        elements.extend(self.create_response_sheet())

        doc.build(elements, onFirstPage=self.draw_header_footer, onLaterPages=self.draw_header_footer)
        return buffer

    def create_teacher_guide(self):
        elements = []
        
        # Add title with horizontal line
        elements.append(HeaderWithLine("TEACHER GUIDE", self.styles['header']))
        elements.append(Spacer(1, 20))
        
        # WALT section
        elements.append(Paragraph("WALT", self.styles['section_header']))
        elements.append(Paragraph(self.data['walt_text'], self.styles['body']))
        elements.append(Spacer(1, 15))
        
        # WILF section
        elements.append(Paragraph("WILF", self.styles['section_header']))
        elements.append(Paragraph(self.data['wilf_text'], self.styles['body']))
        elements.append(Spacer(1, 15))
        
        # TIB section
        elements.append(Paragraph("TIB", self.styles['section_header']))
        elements.append(Paragraph(self.data['tib_text'], self.styles['body']))
        elements.append(Spacer(1, 15))
        
        # Teacher Notes section
        elements.append(Paragraph("Teacher Notes", self.styles['section_header']))
        elements.append(Paragraph(self.data['teacher_notes'], self.styles['body']))
        
        return elements

    def create_task_sheet(self):
        elements = []
        
        # Add title with horizontal line
        elements.append(HeaderWithLine("STUDENT TASK", self.styles['header']))
        elements.append(Spacer(1, 20))
        
        # Student identity section
        identity_data = [
            [Paragraph("Name: __________", self.styles['body']), Paragraph("Date: ________", self.styles['body'])],
        ]
        
        identity_table = Table(identity_data, colWidths=[3*inch, 3*inch])
        identity_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 12),
        ]))
        
        elements.append(identity_table)
        elements.append(Spacer(1, 30))
        
        # WALT section
        elements.append(Paragraph("WALT", self.styles['section_header']))
        elements.append(Paragraph(self.data['walt_text'], self.styles['body']))
        elements.append(Spacer(1, 15))
        
        # TIB section
        elements.append(Paragraph("TIB", self.styles['section_header']))
        elements.append(Paragraph(self.data['tib_text'], self.styles['body']))
        
        return elements

    def create_response_sheet(self):
        elements = []
        
        # Add title with horizontal line
        elements.append(HeaderWithLine("RESPONSE SHEET", self.styles['header']))
        elements.append(Spacer(1, 20))
        
        # Student identity section
        identity_data = [
            [Paragraph("Name: __________", self.styles['body']), Paragraph("Date: ________", self.styles['body'])],
        ]
        
        identity_table = Table(identity_data, colWidths=[3*inch, 3*inch])
        identity_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 12),
        ]))
        
        elements.append(identity_table)
        elements.append(Spacer(1, 30))
        
        # WILF section
        elements.append(Paragraph("WILF", self.styles['section_header']))
        elements.append(Paragraph(self.data['wilf_text'], self.styles['body']))
        elements.append(Spacer(1, 20))
        
        # Practice Words section
        if 'content_data' in self.data and self.data['content_data']:
            elements.append(Paragraph("Practice Words", self.styles['section_header']))
            elements.append(Spacer(1, 10))
            
            for word in self.data['content_data']:
                # Create a table with word and solid underline for writing
                word_data = [
                    [Paragraph(word, self.styles['body']), ""],
                ]
                
                word_table = Table(word_data, colWidths=[2*inch, 4*inch])
                word_table.setStyle(TableStyle([
                    ('ALIGN', (0, 0), (0, 0), 'LEFT'),
                    ('ALIGN', (1, 0), (1, 0), 'LEFT'),
                    ('FONTNAME', (0, 0), (0, 0), 'Helvetica'),
                    ('FONTSIZE', (0, 0), (0, 0), 12),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('PADDING', (0, 0), (-1, -1), 8),
                    # Add solid underline to the second column for writing
                    ('LINEBELOW', (1, 0), (1, 0), 1, HexColor('#000000')),
                ]))
                
                elements.append(word_table)
                elements.append(Spacer(1, 8))
        
        return elements

    
# Example usage:
data = {
    'student_id': '123',
    'task_id': '456',
    'walt_text': 'This is the WALT text',
    'wilf_text': 'This is the WILF text',
    'tib_text': 'This is the TIB text',
    'teacher_notes': 'These are the teacher notes',
    'content_data': ['word1', 'word2', 'word3']
}

pdf = ActivityPDF(data)
buffer = pdf.generate_pdf()
