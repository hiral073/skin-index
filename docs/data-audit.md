# Data audit

A read-only look at the product database, made through the read-only SQLite MCP server and a read-only connection. No data was changed. The data is the March 2023 Sephora US snapshot described in the README, so the findings below are about that snapshot.

| | Count |
|---|---:|
| Products | 1,748 |
| Distinct ingredient names | 5,456 |
| Product-to-ingredient links | 60,810 |

## 1. Ingredient spellings that probably mean the same thing

Ingredient names come from the labels as printed, so the same ingredient is often stored under several spellings. Most of the damage is line breaks and missing spaces from the source text. This matters for the ingredient-name normalizer planned as Step 12a and for any count that groups products by ingredient.

| Kind | Groups or pairs | Names involved |
|---|---:|---:|
| Same name once case, spaces, hyphens and punctuation are ignored | 251 | 586 |
| Close spellings (typos, small word differences), similarity at least 0.93 | 298 pairs | 596 at most |
| Singular and plural of the same name | 6 pairs | 12 |

In the first kind, 335 names are the less common spelling of a name that exists in a more common form. They are used by 765 product-to-ingredient links, so each of those links would count under the wrong name.

### Same name once spacing and punctuation are ignored (the most used 12 of 251 groups)

Each line shows the spelling with the most products first, then the variants, with the number of products that use each.

| Spellings (products) |
|---|
| `Glycerin` (1382); `) Glycerin` (1) |
| `Phenoxyethanol` (991); `Phenoxy Ethanol` (1); `Phenoxy-Ethanol` (1) |
| `Butylene Glycol` (824); `Butyleneglycol` (1); `Bu-Tylene Glycol` (1); `Butyl-ene Glycol` (1) |
| `Tocopherol` (743); `Tocopherol+` (2); `Toco- pherol` (1); `Toco Pherol` (1) |
| `Ethylhexylglycerin` (633); `Ethylhexyl Glycerin` (1); `Ethylhexyl- Glycerin` (1); `Ethylhexylglycer-in` (1) |
| `Xanthan Gum` (629); `XanthanGum` (2) |
| `Caprylyl Glycol` (609); `CaprylylGlycol` (1) |
| `Caprylic/Capric Triglyceride` (549); `Caprylic/ Capric Triglyceride` (3); `Caprylic/Capric Tri-glyceride` (2); `Caprylic /Capric Triglyceride` (1); `Caprylic/Caprictriglyceride` (1); `Caprylic / Capric Triglyceride` (1); `Caprylic Capric Triglyceride` (1) |
| `Sodium Hydroxide` (541); `Sodiumhydroxide` (1); `Sodium Hy- Droxide` (1); `Sodi-um Hydroxide` (1); `So-dium Hydroxide` (1) |
| `Potassium Sorbate` (528); `Pota Ssium Sorbate` (1); `PotassiumSorbate` (1) |
| `Tocopheryl Acetate` (486); `Tocopheryl Ac- etate` (2); `TocopherylAcetate` (1) |
| `Dimethicone` (462); `Dimethi-Cone` (1) |

Some groups are not line-break damage: `Glycerin` has a variant `) Glycerin` (a stray bracket), and `Tocopherol` has `Tocopherol+`.

### Close spellings (typos and small differences)

298 pairs of names have a similarity of at least 0.93 without being equal after cleaning. 104 more pairs differ only in a number (for example a different polymer length) and were left out, because a different number usually means a different ingredient. Examples, most used first:

| More common spelling (products) | Close spelling (products) |
|---|---|
| `Glycerin` (1382) | `Glycerine` (1) |
| `Glycerin` (1382) | `Glycerinm` (1) |
| `Phenoxyethanol` (991) | `Pheno Xyethano` (2) |
| `Sodium Hyaluronate` (673) | `Sodium Hylauronate` (1) |
| `Ethylhexylglycerin` (633) | `Ethyhexylglycerin` (2) |
| `Ethylhexylglycerin` (633) | `Ethylhexlglycerin` (1) |
| `Caprylic/Capric Triglyceride` (549) | `Caprylic/Capric Triglycerides` (9) |
| `Caprylic/Capric Triglyceride` (549) | `Caprylic /Capri Triglyceride` (1) |
| `Sodium Benzoate` (529) | `Sodium Benzate` (1) |
| `Tocopheryl Acetate` (486) | `Tocopherol Acetate` (9) |
| `Glyceryl Stearate` (315) | `Glyceryl Stearate SE` (71) |
| `2-Hexanediol` (330) | `2-Hexandiol` (1) |
| `2-Hexanediol` (330) | `2 Hexanedio` (1) |
| `Glyceryl Stearate` (315) | `Glyceryl Distearate` (4) |

**Not every close pair is the same ingredient.** For a normalizer these need a human decision, not an automatic merge:

| Pair | Why it needs care |
|---|---|
| `Linoleic Acid` (109) and `Linolenic Acid` (40) | Two different fatty acids |
| `Glyceryl Stearate` (315) and `Glyceryl Stearate SE` (71) | Related but different grades |
| `Glyceryl Stearate` (315) and `Glyceryl Distearate` (4) | Different compounds |
| `Tocopherol Acetate` and `Tocopheryl Acetate` | Probably the same ingredient (the second is the standard name) |

### Water

The loader already maps `Water`, `Aqua` and `Eau` to one name. 112 names still contain "water", "aqua" or "eau", and most of them are real, different ingredients (flower waters, witch hazel water, sea water). The ones that look like variants of plain water are:

| Name | Products |
|---|---:|
| `Water` | 1,524 |
| `Purified Water` | 12 |
| `Declustered Water (+)\Aqua\Eau De-Structuree (+)` | 7 |
| `Declustered Water (-)\Aqua\Eau De-Structuree (-)` | 6 |

`Water` is used by 1,524 products. `Purified Water` is a separate name for what is probably the same thing.

### Other patterns

- Singular and plural: `Natural Flavors` / `Natural Flavor`; `CI 77491 (Iron Oxides)` / `CI 77491 (Iron Oxide)`; `Glycine Soja (Soybean) Sterols` / `Glycine Soja (Soybean) Sterol`; `Caprylic/Capric Triglycerides` / `Caprylic/Capric Triglyceride`.
- A ligature in the source text: `Helianthus Annuus (Sunﬂower) Seed Oil` (with the single character ﬂ) is stored separately from the normal spelling (2 products).
- Letter case and similar-looking letters: `Titanium Dioxide (CI 77891)` (125) and `Titanium Dioxide (Cl 77891)` (1, a lower-case L).
- A strength left in the name: `Salicylic Acid 2%` (1) next to `Salicylic Acid` (164). The loader moves strengths out of names, but this entry was left as printed.

## 2. Compare groups with fewer than 5 products

There are 27 compare groups. 8 of them have fewer than 5 products. Groups with fewer than two products are not offered in the Compare picker, and Insights lists only groups with at least 5.

| Compare group | Products | Products in it |
|---|---:|---|
| High Tech Tools › Anti-Aging | 1 | Peptight Tightening Neck Serum Roller (StriVectin) |
| Shop by Concern › Anti-Aging | 1 | Lotus Youth Preseve Rescue Mask Mini (fresh) |
| Sunscreen | 1 | Urban Environment Vita-Clear Sunscreen SPF 42 (Shiseido) |
| Cleansers | 2 | Barrier Culture Cleanser Pre-, Pro- & Postbiotic Face Wash (The Nue Co.); Gentle Hydra-Gel Face Cleanser (NUDESTIX) |
| Teeth Whitening | 2 | GLO to Go Teeth Whitening Pen (GLO Science); Pearly Girl Vegan Teeth Whitening Pen (tarte) |
| Eye Masks | 3 | Avocado Fine Line Eye Cream with Retinol (Glow Recipe); Equilibrium Instant Plumping Eye Mask (Hourglass); Party Recharge Cryo Me Crazy Under-eye Masks (INC.redible) |
| Holistic Wellness | 3 | APHRODISIA Intimate Arousal Cannabis Oil (Flora + Bast); Coconut Milk Bath Soak (Herbivore); Forest Lungs Anti-Stress Fragrance Travel Spray (The Nue Co.) |
| BB & CC Creams | 4 | CC Screen 100% Mineral CC Cream SPF 50 PA++++ (Supergoop!); CC+ Cream Oil-Free Matte with SPF 40 (IT Cosmetics); Cicapair Tiger Grass Color Correcting Treatment SPF 30 (Dr. Jart+); and 1 more |

Separately, 99 products have no compare group at all. They are all Mini Size products, which mix every kind of product and are never compared:

| Category | Products |
|---|---:|
| Mini Size | 99 |

## 3. Products with a missing price or size

**In the database there are none.** The loader drops a product when its price or its size is missing or cannot be turned into millilitres, so every stored product has a price, a size and a price per ml:

| Check on the 1,748 stored products | Count |
|---|---:|
| `price IS NULL` | 0 |
| `price <= 0` | 0 |
| `size_text NULL or blank` | 0 |
| `size_ml IS NULL` | 0 |
| `size_ml <= 0` | 0 |
| `price_per_ml IS NULL` | 0 |

The missing and unusable values are in the source file. Of its 2,420 skincare rows, only 1,748 were loaded. 645 skincare rows were dropped for a missing or unusable size, and none for a missing price (every skincare row in the source has a price). Reasons the loader gave:

| Reason (rows in the source file) | Rows |
|---|---:|
| missing size | 365 |
| size not readable (count, set, tool) | 148 |
| size is weight (oz/g), not volume | 121 |
| multipack size | 11 |
| no ingredients listed | 23 |
| duplicate product | 4 |

Examples of dropped rows, with the size text as printed in the source:

| Reason | Product | Brand | Size text | Price (USD) |
|---|---|---|---|---:|
| missing size | Triple Algae Eye Renewal Balm Eye Cream | Algenist | (blank) | 68.00 |
| missing size | 10 Day Results Kit | Algenist | (blank) | 88.00 |
| missing size | Plump Pout Duo | Algenist | (blank) | 44.00 |
| size not readable (count, set, tool) | Bright Eyes Collagen-Infused Brightening Colloidal Silver Eye Masks | BeautyBio | 15 pairs | 40.00 |
| size not readable (count, set, tool) | GloPRO Prep Pads Clarifying Skin Cleansing Wipes with Peptides | BeautyBio | 30 pads | 39.00 |
| size not readable (count, set, tool) | The Canopy Humidifier Starter Set | CANOPY | Starter Set / Cream | 150.00 |
| multipack size | R45 The Lift 3-Phase Advanced Neck Contouring Treatment | BeautyBio | 3 x 0.17 oz/ 5 mL | 85.00 |
| multipack size | Aqua Bomb Mist | belif | 2 x 2.02 oz/ 60 mL | 38.00 |
| multipack size | Fresh Pressed Renewing Powder Cleanser with Pure Vitamin C | CLINIQUE | 28 x 0.01 oz/ 0.5 g packets | 39.00 |
| size is weight (oz/g), not volume | The Quench Eye Reviving Quadralipid Eye Balm | BeautyBio | 5 oz/ 14 g | 99.00 |
| size is weight (oz/g), not volume | Aqua Bomb Overnight Lip Mask | belif | .7 oz/ 20 g | 22.00 |
| size is weight (oz/g), not volume | Acne Solutions Cleansing Bar For Face and Body | CLINIQUE | 5.2 oz/ 147 g | 19.50 |

The largest group, 365 rows with a blank size, is mostly gift sets and tools: 192 are in Value & Gift Sets, 68 in High Tech Tools and 35 in Wellness. A price per ml cannot be worked out for any of them without guessing, and the app deliberately does not guess. The 121 rows with a weight in place of a volume (for example `5 oz/ 14 g` for an eye balm) are balms, bars and sticks.

## 4. Group cleanup

Section 2 found 27 compare groups, several of them splits of one product type or not product types at all. The loader now applies a cleanup map after it builds each product's group from the category levels. The map is in `content/compare_groups.py` (`GROUP_MERGES` and `HIDDEN_GROUPS`), so rebuilding the database with `python -m database.load_data` gives the same result. The original `category` column is not changed, no product is deleted (1,748 before and after), and the other tables (for example `exchange_rates`) are not touched.

Where it shows: Compare, the Compare picker, Insights and the Products page Category filter and column read the new groups. The product detail page still shows the original category. The Today page's "Browse cleansers" link goes to "Face Wash & Cleansers".

Some groups have subcategories, written "Sunscreen › Face". A subcategory is a group of its own for Compare and Insights (a face and a body sunscreen are not compared with each other). In the three dropdowns (Products, Compare, Insights) the parent is one heading with its subcategories under it; the Products dropdown also has "All Sunscreen", which lists the parent's subcategories together.

| Old group | New group | Products | Group size after |
|---|---|---:|---:|
| Face Sunscreen | Sunscreen › Face | 85 | 85 |
| Body Sunscreen | Sunscreen › Body | 9 | 9 |
| Sunscreen (no third level) | Sunscreen (no subcategory) | 1 | 1 |
| For Face | Self Tanners › Face | 17 | 17 |
| For Body | Self Tanners › Body | 26 | 26 |
| Cleansers (no third level) | Face Wash & Cleansers | 2 | 198 (was 196) |
| Eye Masks | Eye Creams & Treatments | 3 | 153 (was 150) |
| Night Creams | unchanged, stays its own group | 17 | 17 |
| Shop by Concern › Anti-Aging | no group | 1 | |
| High Tech Tools › Anti-Aging | no group | 1 | |
| Holistic Wellness | no group | 3 | |
| Teeth Whitening | no group | 2 | |

Why these:
- **Sunscreen and Self Tanners**: each is one product type with a face and a body kind, so the parent keeps both and each kind is a subcategory. For self-tanners the retailer's face/body split is not consistent (a "Face & Body" gel is under For Body, a "Face & Body" drops product under For Face), so these follow the retailer's grouping as it is. The one sunscreen with no third level (Urban Environment Vita-Clear, Shiseido) is not put in a subcategory, because the data does not say face or body.
- **Face Wash & Cleansers and Eye Creams & Treatments**: the merged groups were small variants of these (two face cleansers with no third level, eye masks).
- **No group**: the two Anti-Aging groups hold one product each (a neck-serum roller and a mini mask), and Holistic Wellness (bath soak, cannabis oil, fragrance spray) and Teeth Whitening are not skincare product types. These products are not compared, are not in the Compare picker and are not in an Insights group. Their `category` is unchanged.
- **Kept separate on purpose**: Night Creams (17), Makeup Removers (7: cleansing balms, micellar water, eye makeup remover) and BB & CC Creams (4: tinted creams with SPF). None is merged into another group. No product was moved out of Face Wash & Cleansers by name, so about 30 cleansing balms, micellar waters and makeup-remover cleansers stay there.

| | Before | After |
|---|---:|---:|
| Compare groups | 27 | 21 |
| Groups with fewer than 5 products | 8 | 2 (BB & CC Creams 4, Sunscreen with no subcategory 1) |
| Groups with fewer than 2 products (not in the picker) | 3 | 1 (Sunscreen with no subcategory) |
| Products with no group | 99 | 106 (the 99 Mini Size products and the 7 above) |
| Products in total | 1,748 | 1,748 |

Not changed by this cleanup: other groups with clearly different product types stay apart (Toners and Mists & Essences, Exfoliators and Facial Peels, and so on). Some products named "Mini", "Travel" or "Duo" still sit in real groups, because their category says so; they were not checked one by one.

## What was not changed

Sections 1 to 3 are findings only: nothing in the database or the source file was changed by the audit. The server opens the database in SQLite's read-only mode and the audit used a read-only connection. The database file's checksum was identical before and after. Section 4 is the one change made afterwards, in the loader.
