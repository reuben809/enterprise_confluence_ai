from ingestion import confluence_crawler, embedder
print("🧭 Crawling Confluence...")
confluence_crawler.crawl()
print("📚 Generating embeddings & storing in Qdrant...")
embedder.run()
print("✅ Ingestion complete.")
