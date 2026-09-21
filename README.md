# BIOENDO Korea Website

Official website for BIOENDO Korea (Global Biotech).
Live: [bioendokorea.com](https://bioendokorea.com)

## Structure
- `index.html` — Home (V6)
- `about.html` — Company introduction
- `inquiry.html` — Contact form (FormSubmit.co)
- `coa.html` — Lot-based CoA lookup and download
- `coa-admin.html` — Token-protected CoA registration screen (noindex)
- `product-*.html` — Product detail pages (KC, KT, EC, GC, rFC, rCR)
- `server-coa/` — Isolated Hostinger CoA API, importer, and service configuration
- `css/style.css` — Shared product page styles
- `images/` — Logos, favicons, CDN backup assets

## Deployment
Auto-deployed to Vercel on every push to `main`.
- Domain: bioendokorea.com
- Project: bioendo-kr

The `/api/coa/*` path is proxied by Vercel to the company Hostinger server. CoA files and the SQLite index are not stored in this public repository.

## Contact
- Global Biotech · +82-2-406-4387
- sales@chcrmkorea.com
