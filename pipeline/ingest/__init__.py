"""Layer ingestion (spec §5). Each module pulls one layer and returns a list of
normalised Records. All network access lives here and in Tier A only; nothing
here runs on Netlify.
"""
