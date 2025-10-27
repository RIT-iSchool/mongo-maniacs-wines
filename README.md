# **Wine Cellar Search Application**

*A Flask–MongoDB Geospatial and Text Search Web Application*

---

## **1\. Technology Stack**

### **Backend**

* **Python (Flask Framework):**  
   Flask was chosen for its minimalist design and fine-grained control over routing, templating, and session handling. Its modular nature allows rapid development of data-driven web applications while maintaining a clean separation between presentation and logic.

* **MongoDB:**  
   A NoSQL database was used to store and query heterogeneous wine data. MongoDB’s document structure enables storage of unstructured attributes (e.g., variable tasting notes) and provides native **geospatial** and **text search** capabilities that are important to this project.

* **PyMongo and GridFS:**  
   The `pymongo` library provided efficient communication with the MongoDB instance. `GridFS` was utilized to store and retrieve image data (country flags) directly within the database, maintaining portability and eliminating file-system dependencies.

### **Frontend**

* **HTML5:**  
   The interface was built from scratch using HTML, prioritizing readability and simpleness. The dark theme integration satisfies both accessibility and aesthetic requirements.


### **Rationale for Stack Selection**

The chosen architecture balances **simplicity**, **scalability**, and **expressiveness**:

1. Flask’s micro-framework approach enables rapid iteration.

2. MongoDB supports both **textual** and **geospatial** indexing in a single system.

3. GridFS centralizes all project assets (text, data, and images) within one coherent datastore.

4. The stack transitions naturally to a cloud-ready or containerized environment without refactoring.

---

## **2\. Process**

The dataset was collected from kaggle containing 130,000 documents and then was filtered down to 119,788 documents after removing the N/A values as well as strings that have little meaning. Loaded data into the database, joined country flag image as well as the lat/lon coordinates. 

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

* **Hierarchical Query Resolution:**  
   Each unique location was geocoded at three levels of specificity:

  1. `(region_1, province, country)`

  2. `(province, country)`

  3. `(country)`

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

If an entry failed at the region level, the system automatically retried at province, then country level.

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
 After processing, **49 075 records** contained verified coordinates and clean metadata, forming the final dataset used for application deployment.

---

## **3\. Volume**

The collection size was verified post-import:

`db.wines.countDocuments()`

**Result:** `119,788 documents` in the `wines` collection.

This scale enabled realistic testing of MongoDB’s geospatial and text indexing while maintaining responsive Flask performance.

---

## **4\. Variety**

The dataset supports rich semantic and geographic variety. The following search terms highlight this diversity:



---

## **5\. Bells and Whistles**

### **Highlights**

1. **Integrated Geospatial \+ Text Search:**  
    The application unifies `$text` and `$geoWithin` queries, allowing multi-dimensional filtering by both semantic and spatial criteria.

2. **Dynamic and Aesthetic UI:**  
    Custom CSS styling introduces light/dark mode contrast, animated transitions, and a focus on readability.

3. **GridFS Media Integration:**  
    Country flags are stored and streamed directly from MongoDB, ensuring full portability.

4. **Persistent Commenting System:**  
    User comments are appended to the relevant wine document as an embedded array with timestamps.

5. **Performance Optimization:**  
    Compound indices on `country`, `variety`, and `location` improve query speed and scalability.

### **What We Are Most Proud Of**

* The **harmonization of geospatial intelligence and text analytics** in a single, user-friendly web interface.

* A **modular codebase** emphasizing clarity and extensibility.

* The **research-grade data preparation pipeline**, which geocoded tens of thousands of records using open data principles while adhering to ethical rate-limit standards.

---

## **6\. Running the Application**

### **Setup**

`pip install flask pymongo geopy pandas`  
`python3 app.py`

Ensure MongoDB is running locally and contains the geocoded dataset.

Navigate to [http://localhost:3000](http://localhost:3000) in your browser to access the search interface.

