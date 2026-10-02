import fitz
doc = fitz.open("book_temp.pdf")
print("Pages:", doc.page_count)
toc = doc.get_toc()
print("Number of TOC entries:", len(toc))
for entry in toc:
    print(entry)
doc.close()
