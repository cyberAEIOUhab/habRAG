import sys
# Try multiple PDF libraries
for mod_name in ['pypdf', 'PyPDF2', 'pdfminer', 'pdfplumber', 'pikepdf']:
    try:
        mod = __import__(mod_name)
        print(f"{mod_name} available")
    except ImportError:
        print(f"{mod_name} not available")
