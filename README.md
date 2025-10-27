# **Wine Cellar Search Application**

*A Flask–MongoDB Geospatial and Text Search Web Application*

---

## **1\. Technology Stack**

### **Backend**

* **Python (Flask Framework):**  
   Flask was chosen for its minimalist design and fine-grained control over routing, templating, and session handling. Its modular nature allows rapid development of data-driven web applications while maintaining a clean separation between presentation and logic.

* **MongoDB:**  
   A schema-flexible NoSQL database was used to store and query heterogeneous wine data. MongoDB’s document structure enables storage of unstructured attributes (e.g., variable tasting notes) and provides native **geospatial** and **text search** capabilities critical to this project.

* **PyMongo and GridFS:**  
   The `pymongo` library provided efficient communication with the MongoDB instance. `GridFS` was utilized to store and retrieve image data (such as country flags) directly within the database, maintaining portability and eliminating file-system dependencies.

### **Frontend**

* **HTML5 (Custom UI Design):**  
   The interface was built from scratch using HTML, prioritizing readability and responsiveness. The dark/light theme integration satisfies both accessibility and aesthetic usability requirements.

### **Rationale for Stack Selection**

The chosen architecture balances **simplicity** and **scalability**:

1. Flask’s framework approach enables rapid iteration.

2. MongoDB supports both **textual** and **geospatial** indexing in a single system.

3. GridFS centralizes all project assets (text, data, and images) within one coherent datastore.

---

## **2\. Process**

The dataset was preprocessed and augmented through a multi-stage pipeline involving data cleaning, geolocation enrichment, normalization, and database ingestion. This ensured each document contained both textual metadata and accurate geographic coordinates for spatial querying.

### **Step 1 — Source Data and Initial Cleaning**

The raw dataset (`wine_reviews.csv`) was loaded into a Pandas DataFrame. Columns were normalized and trimmed of whitespace, and rows missing essential location information (e.g., `country`) were removed.

`import pandas as pd`  
`temp_df = pd.read_csv("wine_reviews.csv")`  
`temp_df['country'] = temp_df['country'].str.strip().fillna('')`  
`temp_df['province'] = temp_df['province'].str.strip().fillna('')`

---

### **Step 2 — Geolocation via Nominatim (OpenStreetMap)**

Because the dataset lacked latitude and longitude coordinates, a custom **geocoding pipeline** was built using the **Nominatim API** via the `geopy` library.

#### **Key Design Features**

* **Query Resolution:**  
   Each unique location was geocoded at the level of specificity shown below:

  1. `(province, country)`

* **Rate Limiting and Backoff:**  
   To comply with Nominatim’s usage policy, a delay of 1.6 s per request was imposed and exponential backoff used for transient 503 errors.

* **Caching:**  
   A persistent JSON cache (`nominatim_cache.json`) prevented redundant API calls and enabled recovery from interrupted runs.

Example snippet:

`from geopy.geocoders import Nominatim`  
`from geopy.extra.rate_limiter import RateLimiter`

`geo = Nominatim(user_agent="wine-geocoder (keerthanpanyala7@gmail.com)")`  
`geocode = RateLimiter(geo.geocode, min_delay_seconds=1.6, swallow_exceptions=True)`

`location = geocode("Mendoza, Argentina")`  
---

### **Step 3 — Secondary Verification**

A secondary script, using `requests.get()` with the Nominatim REST API, re-attempted geolocation for records that failed in the primary pass.

`params = {'q': f"{province}, {country}", 'format': 'json', 'limit': 1}`  
`r = requests.get('https://nominatim.openstreetmap.org/search', params=params,`  
                 `headers={'User-Agent': 'wine-reviews (contact: keerthanpanyala7@gmail.com)'})`

This secondary validation increased geolocation coverage and ensured all results adhered to API rate-limit constraints.

---

### **Step 4 — Integration and Merging**

The resulting coordinate data (`geocoded_locations.csv`) was merged with the original dataset using a composite key of `country` \+ `province`. Duplicates were removed, and missing or inconsistent entries were filtered out:

`merged_df = pd.merge(`  
    `df_reviews,`  
    `df_geo[['country', 'province', 'latitude', 'longitude']].drop_duplicates(),`  
    `on=['country', 'province'],`  
    `how='left'`  
`)`

---

### **Step 5 — Final Cleaning and Export**

Records missing coordinates were dropped, and redundant columns such as `region_1` were removed:

`check_df_cleaned = merged_df.dropna(subset=['latitude', 'longitude']).drop('region_1', axis=1)`

The cleaned dataset was exported as both CSV and JSON for ingestion into MongoDB:

`check_df_cleaned.to_csv("wine_reviews_lat_long.csv", index=False)`  
`check_df_cleaned.to_json("wine_reviews.json", orient='records', lines=True)`

---

### **Step 6 — Database Loading and Enrichment**

The cleaned JSON dataset was imported into MongoDB:

`mongoimport --db wine_db --collection wines --file wine_reviews.json --jsonArray`

Each record was augmented with a GeoJSON-compliant `location` field:

`db.wines.updateMany(`  
  `{ latitude: { $type: "number" }, longitude: { $type: "number" } },`  
  `[ { $set: { location: { type: "Point", coordinates: [ "$longitude", "$latitude" ] } } } ]`  
`)`  
`db.wines.createIndex({ location: "2dsphere" })`  
`db.wines.createIndex({ title: "text", description: "text", variety: "text", winery: "text" })`

---

### **Challenges and Mitigation**

| Challenge | Mitigation |
| ----- | ----- |
| Nominatim rate limits and HTTP 503 errors | Implemented 1.6 s delay and exponential backoff with caching |
| Inconsistent geographic fields | Used hierarchical fallback (region → province → country) |
| Malformed or numeric-only values | Input sanitation via regular expressions |
| Partial coverage | Combined API calls and cache re-use to reach \~92 % geolocation success |
| Join collisions on merge | Dropped duplicate `(country, province)` pairs before merge |

---

**Outcome:**  
 After processing, around **120,000 records** contained verified coordinates and clean metadata, forming the final dataset used for application deployment.

---

## **3\. Volume**

The collection size was verified post-import:

`db.wines.countDocuments()`

**Result:** `119788 documents` in the `wines` collection.

This scale enabled realistic testing of MongoDB’s geospatial and text indexing while maintaining responsive Flask performance.

---

## **4\. Variety**

The dataset supports rich semantic and geographic variety. The following search terms highlight this diversity:

| Search Query | Observation |
| ----- | ----- |
| `"Pinot Noir"` | Demonstrates varietal diversity across Oregon and Burgundy regions. |
| `"honey"` | Captures dessert-wine descriptions via full-text search. |
| `"Riesling"` | Combines text and geospatial filters to isolate wines in Germany’s Mosel Valley. |
| `"Mendoza"` (lat −32.89, lon −68.83, radius 100 km) | Spatial query isolates Argentinian Malbec producers. |
| `"Chardonnay" AND "California"` | Compound query combining textual and location constraints. |

**User Interaction Example:**  
 A search for *“Pinot Noir” near latitude 45.52, longitude −122.67* returns Oregon wineries. Selecting a record opens a detailed page showing a country flag (served via GridFS) and user-added comments stored directly within the document.

---

### 

### 

### **Interesting Search Terms & Behaviors**

The application supports both **text-based** and **geo-based** search. The following search terms yield particularly notable results:

**Oregon Pinot cluster**

Field: Variety → Query: Pinot Noir

Country: US · Province: Oregon

Geospatial Mode: Center on Country/Province · Radius: 120 km

Finds Oregon Pinot Noir clusters

**Riesling around the Great Lakes**

Field: Variety → Riesling

Country: US · Province: Michigan

Mode: Center on Country/Province · Radius: 150 km

Finds Lake Michigan Shore / Old Mission Peninsula bottlings.

## **5\. Bells and Whistles**

### **Highlights**

1. **Integrated Geospatial \+ Text Search:**  
    The application combines `$text` and `$geoWithin` queries, allowing multi-dimensional filtering by both semantic and spatial criteria.

2. **Dynamic and Aesthetic UI:**  
    Custom styling introduces light/dark mode contrast, animated transitions, and a focus on readability.

3. **GridFS Media Integration:**  
    Country flags are stored and retrieved directly from MongoDB.

4. **Persistent Commenting System:**  
    User comments are appended to the relevant wine document as an embedded array with timestamps.

5. **Performance Optimization:**  
    Indices on `country`, `variety`, `location and description` improve query speed and scalability.

### **What We Are Most Proud Of**

* The **combination of geospatial and text search** in a single, user-friendly web interface.

* The **data preparation pipeline**, which geocoded tens of thousands of records using open data principles while adhering to ethical rate-limit standards.  
* The **ease of use** and **fast retrieval** of documents while using the application

---

## **6\. Running the Application**

### **Setup**

`pip install flask pymongo geopy pandas`  
`python3 app.py`

Ensure MongoDB is running locally and contains the geocoded dataset.

Navigate to [https://mongo-maniacs.webdev.gccis.rit.edu/](https://mongo-maniacs.webdev.gccis.rit.edu/) in your browser to access the search interface.

