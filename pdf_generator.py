from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from io import BytesIO
import svglib
from reportlab.graphics import renderPDF, renderPM

class ActivityPDF:
    def __init__(self, data):
        self.data = data
        self.styles = getSampleStyleSheet()
        self.styles.add(ParagraphStyle(name='header', fontSize=18, leading=22, alignment=1, fontName='Helvetica-Bold'))
        self.styles.add(ParagraphStyle(name='body', fontSize=12, leading=14, alignment=0, fontName='Helvetica'))

    def generate_pdf(self):
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        elements = []

        # Page 1: Teacher's Guide
        elements.append(self.create_teacher_guide())
        elements.append(Spacer(1, 12))

        # Page 2: Task Sheet
        elements.append(self.create_task_sheet())
        elements.append(Spacer(1, 12))

        # Page 3: Response Sheet
        elements.append(self.create_response_sheet())
        elements.append(Spacer(1, 12))

        doc.build(elements)
        return buffer

    def create_teacher_guide(self):
        elements = []
        elements.append(Paragraph("WALT: " + self.data['walt_text'], self.styles['body']))
        elements.append(Paragraph("WILF: " + self.data['wilf_text'], self.styles['body']))
        elements.append(Paragraph("TIB: " + self.data['tib_text'], self.styles['body']))
        elements.append(Paragraph("Teacher Notes: " + self.data['teacher_notes'], self.styles['body']))
        elements.append(Image("/logo.svg", width=1 * inch, height=1 * inch))
        elements.append(Image("origami_swan.png", width=1 * inch, height=1 * inch, hAlign='RIGHT'))
        elements.append(self.create_footer_qr())
        return [item for item in elements]

    def create_task_sheet(self):
        elements = []
        elements.append(Paragraph("WALT: " + self.data['walt_text'], self.styles['body']))
        elements.append(Paragraph("TIB: " + self.data['tib_text'], self.styles['body']))
        elements.append(self.create_footer_qr())
        return [item for item in elements]

    def create_response_sheet(self):
        elements = []
        elements.append(Paragraph("WILF: " + self.data['wilf_text'], self.styles['body']))
        elements.append(self.create_footer_qr())
        return [item for item in elements]

    def create_footer_qr(self):
        # Create QR code
        qr_code = "https://unboxed-learning.streamlit.app/?student_id=" + self.data['student_id'] + "&task=" + self.data['task_id']
        return [Paragraph(qr_code, self.styles['body'])]

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
