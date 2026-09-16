# Xifeng public CAD resource follow-up

Date: 2026-09-16. Scope: public links only; no Xifeng VIP access,
account login, cloud save action, or archive download was performed.

## Correction to the initial discovery

The first probe missed older competition posts advertising drawings AND
model answers. It also treated any article containing a VIP notice as
entirely gated, even when that article exposed a separate limited-free link.
The parser now distinguishes mixed public links and gated sections. Public
links still require inspection; their presence is not download verification.

## Reproducible evidence

- `.local/posttrain/xifeng-step-discovery-r1/catalog.json`: 12 articles.
- `.local/posttrain/xifeng-step-discovery-r2/catalog.json`: 8 more articles.
- Adjacent `fetch-audit.json` files record article response hashes and sizes.
- `evals/posttrain/probe_xifeng_cad.py` records advertised claims separately
  from actual anonymous cloud file listings. It retains no ephemeral tokens.
- A headless Chrome visit to the first competition share successfully listed
  the ZIP; selecting it and clicking Download displayed a login dialog.
  Anonymous listing is therefore not proof of anonymous download.

## Live public candidate links

These seven shares returned successful anonymous file listings. No archive
contents or actual STEP geometry have been inspected.

1. First competition, return valve: https://xifengboke.com/post/2300.html
   Share: https://pan.quark.cn/s/07bb017aa43a
   ZIP: 5,225,846 bytes. Article advertises drawings plus model answers.
2. Second competition, hand-operated valve: https://xifengboke.com/post/2301.html
   Share: https://pan.quark.cn/s/c4ff9790e629
   ZIP: 6,434,380 bytes. Article advertises PDF task plus model answers.
3. Nineteenth provincial competition: https://xifengboke.com/post/2574.html
   Share: https://pan.quark.cn/s/b61b7dfe6e37 (public code YCXK).
   Listing includes two PDFs (72,242 and 948,512 bytes) and a supplied-parts
   ZIP (109,922 bytes). Article explicitly describes 15 STP supplied parts,
   32 parts overall, and seven drawing sheets. Supplied parts are NOT the
   complete reconstruction answer or verified full-assembly ground truth.
4. GGD cabinet: https://xifengboke.com/post/2458.html
   Share: https://pan.quark.cn/s/2a39b39805a0 (public code F4ey).
   ZIP: 74,294,955 bytes. Article describes editable SolidWorks 2014 models;
   it does not establish STEP availability. Public and VIP links coexist.
5. Control console: https://xifengboke.com/post/2501.html
   Share: https://pan.quark.cn/s/b07770b53277?pwd=AfcA
   RAR: 12,703,724 bytes. Article describes SolidWorks 2010 model parameters;
   STEP format is not verified. Public and VIP links coexist.
6. Ring-network electrical cabinet: https://xifengboke.com/post/2468.html
   Share: https://pan.quark.cn/s/961077661796 (public code KJ9H).
   HXGN-12 model ZIP: 28,408,664 bytes. Format remains unverified.
7. Heavy-duty rack: https://xifengboke.com/post/2477.html
   Share: https://pan.quark.cn/s/e2c29d7b77db?pwd=71Qf
   The listing actually returns HXGN-12, with the SAME filename and byte
   count as item 6. Suspected wrong article link or duplicate; exclude from
   training intake until resolved. Equality of file hashes was not checked.

## Invalid or incomplete candidates

- Eighteenth provincial compressor, post 2292, explicitly advertises ten
  drawings and 18 STP standard parts. Its Quark share returned HTTP 404,
  API code 41010, and a provider message stating the file involved prohibited
  content. Do not count it as currently downloadable. The article also lists
  a Baidu alternative, whose file download was not verified.
- Food dicing machine, post 2378, advertises three drawings and two STP
  supplied files containing multiple components. Its Quark share returned
  the same 404/41010 response. Do not count advertised parts as acquired data.
- Other old competition links include failed cloud requests and a Baidu-only
  share. The raw catalogs preserve per-article status; HTTP errors alone
  must not be generalized into a claim that every alternative is dead.

## Intake boundary and next step

Downloaded CAD files: zero. Verified drawing/CAD ground-truth pairs: zero.
The useful next step is normal user-authenticated download of the live
competition packages, followed by archive inventory, STEP/BRep validation,
units, assembly/part separation, and drawing-to-part matching. Do not run
executables, macros, or scripts found inside third-party archives.

No data has been imported into training. The site's notice reserves original
author rights and describes short-term noncommercial inspection, not an
explicit training or redistribution license. Record original-source rights
before retaining a research dataset.
