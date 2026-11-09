"""Document reading module: uploaded books -> page text -> structure, mentions and source checks.

Command line (used by Claude Code when extracting knowledge, see CLAUDE.md):
  python -m document_reader read <file in documents/uploaded_books>   extract text + print the report
  python -m document_reader read --all                                  every uploaded document
  python -m document_reader check                                       verify every source quote in the knowledge base
"""
