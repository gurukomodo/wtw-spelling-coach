from pdf_generator import ActivityPDF

data = {
    'student_id': 'STU_6264',
    'task_id': 'TASK_123',
    'walt_text': 'Identify the \'ch\' phoneme in common words.',
    'wilf_text': 'Correct placement of \'ch\' at the start and end of words.',
    'tib_text': 'This helps us read and write words like \'chip\' and \'rich\'.',
    'teacher_notes': 'Please review the words with the student.',
    'content_data': ['chip', 'rich', 'much', 'chop']
}

pdf = ActivityPDF(data)
buffer = pdf.generate_pdf()

with open('test_output.pdf', 'wb') as f:
    f.write(buffer.getvalue())
