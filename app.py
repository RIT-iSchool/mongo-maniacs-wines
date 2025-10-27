#!/usr/bin/env python3
import os
import re
import datetime
from flask import Flask, render_template, request, Response, redirect, url_for, g, jsonify
from pymongo import MongoClient, ASCENDING, DESCENDING # Import sorting directions
from bson import ObjectId
import gridfs
from gridfs.errors import NoFile


# --- 1) CONFIG ---
# MONGO_URI = "mongodb://localhost:27017/"
MONGO_URI = "mongodb://mongoapp:huMONGOu5@localhost:27017/appdb?authSource=appdb"
DB_NAME = "appdb"
COLLECTION_NAME = "wines"
GRIDFS_BUCKET = "flags"


app = Flask(__name__)


# --- 2) DB HELPERS ---
def get_db():
    if "db" not in g:
        client = MongoClient(MONGO_URI)
        g.db = client[DB_NAME]
    return g.db


def get_fs():
    if "fs" not in g:
        g.fs = gridfs.GridFS(get_db(), collection=GRIDFS_BUCKET)
    return g.fs


@app.teardown_appcontext
def teardown_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.client.close()


# --- 3) UTILS ---
def regex_safe(s: str) -> str:
    """Escapes regex special characters."""
    return re.escape(s or "")


def km_to_meters(km: str) -> float:
    """Converts km string to meters float, returns 0 on error."""
    try:
        return float(km) * 1000.0
    except Exception:
        return 0.0


def get_filter_lists(db, max_items=250):
    """Gets sorted lists of distinct countries and provinces."""
    coll = db[COLLECTION_NAME]
    countries = sorted([c for c in coll.distinct("country") if c], key=str)[:max_items]
    provinces = sorted([p for p in coll.distinct("province") if p], key=str)[:max_items]
    return countries, provinces


def centroid_for(db, country=None, province=None):
    """Computes a centroid [lon, lat] for a given area."""
    coll = db[COLLECTION_NAME]
    match = {}
    if country: match["country"] = country
    if province: match["province"] = province


    pipeline = [
        {"$match": match} if match else {"$match": {}},
        {"$match": {"location.type": "Point"}},
        {"$group": {
            "_id": None,
            "lon": {"$avg": {"$arrayElemAt": ["$location.coordinates", 0]}},
            "lat": {"$avg": {"$arrayElemAt": ["$location.coordinates", 1]}}
        }}
    ]
    try:
        agg = list(coll.aggregate(pipeline))
        if agg and agg[0].get("lon") is not None and agg[0].get("lat") is not None:
            return [float(agg[0]["lon"]), float(agg[0]["lat"])]
    except Exception as e:
        print(f"Centroid calculation error: {e}")
    return None


def get_country_stats(db, country_name: str):
    """Calculates avgPrice, avgPoints, and topVariety for a specific country."""
    if not country_name:
        return None


    coll = db[COLLECTION_NAME]
    pipeline = [
        {"$match": {"country": country_name}},
        {"$facet": {
            "avgStats": [
                {"$group": {
                    "_id": None,
                    "avgPrice": {"$avg": "$price"},
                    "avgPoints": {"$avg": "$points"}
                }}
            ],
            "varietyCounts": [
                {"$match": {"variety": {"$ne": None, "$ne": ""}}},
                {"$group": {"_id": "$variety", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 1}
            ]
        }},
        {"$project": {
            "avgPrice": {"$ifNull": [{"$arrayElemAt": ["$avgStats.avgPrice", 0]}, None]},
            "avgPoints": {"$ifNull": [{"$arrayElemAt": ["$avgStats.avgPoints", 0]}, None]},
            "topVariety": {"$ifNull": [{"$arrayElemAt": ["$varietyCounts._id", 0]}, None]},
        }}
    ]


    try:
        results = list(coll.aggregate(pipeline))
        if results:
            return results[0]
        else:
             return {"avgPrice": None, "avgPoints": None, "topVariety": None}
    except Exception as e:
        print(f"Error calculating stats for {country_name}: {e}")
        return None


# --- 4) ROUTES ---
@app.get("/")
def index():
    """Renders the initial search page."""
    countries, provinces = get_filter_lists(get_db())
    return render_template(
        "search.html",
        q="", field="all", use_text=False,
        country="", province="",
        geo_mode="by_area", lat="", lon="", radius="50",
        sort_by="points_desc", # Default sort
        results=[], total=0,
        countries=countries, provinces=provinces,
        stats=None
    )


@app.get("/search")
def search():
    """Handles search requests and renders results with optional stats and sorting."""
    db = get_db()
    coll = db[COLLECTION_NAME]


    # --- Get inputs ---
    q = (request.args.get("q") or "").strip()
    field = (request.args.get("field") or "all").strip()
    use_text = (request.args.get("text") or "") == "1"
    country_filter = (request.args.get("country") or "").strip()
    province_filter = (request.args.get("province") or "").strip()
    geo_mode = (request.args.get("geo_mode") or "by_area").strip()
    lat_str = (request.args.get("lat") or "").strip()
    lon_str = (request.args.get("lon") or "").strip()
    radius_str = (request.args.get("radius") or "50").strip()
    max_m = km_to_meters(radius_str)
    # --- Get sort parameter, default to points_desc ---
    sort_by = (request.args.get("sort_by") or "points_desc").strip()


    # --- Build query filters ---
    filters = []
    # (Text search logic)
    if q:
        if use_text: # Use $text index if checked AND query exists
            filters.append({"$text": {"$search": q}})
        else: # Otherwise use regex
            r = re.compile(regex_safe(q), re.IGNORECASE)
            if field == "all":
                filters.append({"$or": [{"title": r}, {"description": r}, {"winery": r}, {"variety": r}]})
            elif field in ("title", "description", "variety", "winery"):
                 filters.append({field: r})


    # (Facet filters)
    if country_filter: filters.append({"country": country_filter})
    if province_filter: filters.append({"province": province_filter})


    # (Geospatial logic)
    center_coords = None
    if geo_mode == "by_area" and max_m > 0 and (country_filter or province_filter):
        center_coords = centroid_for(db, country=country_filter or None, province=province_filter or None)
        if center_coords:
            filters.append({"location": {"$geoWithin": {"$centerSphere": [center_coords, max_m / 6378100.0]}}})
    elif geo_mode == "by_coords" and max_m > 0 and lat_str and lon_str:
        try:
            lat = float(lat_str); lon = float(lon_str)
            center_coords = [lon, lat]
            filters.append({"location": {"$geoWithin": {"$centerSphere": [center_coords, max_m / 6378100.0]}}})
        except ValueError: pass


    # --- Combine filters, projection ---
    query = {"$and": filters} if filters else {}
    projection = { "title": 1, "country": 1, "province": 1, "variety": 1, "winery": 1, "points": 1, "price": 1, "country_image": 1 }
    # NOTE: $text score projection is removed as relevance sort is removed


    # --- Determine sort order (Price/Points only) ---
    sort_order = []
    if sort_by == "price_asc":
        sort_order.append(("price", ASCENDING))
    elif sort_by == "price_desc":
        sort_order.append(("price", DESCENDING))
    elif sort_by == "points_asc":
        sort_order.append(("points", ASCENDING))
    # Default to points_desc if sort_by is invalid or not set
    else: # Default case includes sort_by == "points_desc"
        sort_order.append(("points", DESCENDING))


    # --- Execute main search ---
    total = coll.count_documents(query)
    cursor = coll.find(query, projection)
    # Apply sort if defined (will always be defined now with default)
    cursor = cursor.sort(sort_order)
    results = list(cursor.limit(50))


    # --- Calculate country stats ---
    country_stats = get_country_stats(db, country_filter) if country_filter else None


    # --- Get dropdown lists ---
    countries, provinces = get_filter_lists(db)


    # --- Render template ---
    return render_template(
        "search.html",
        q=q, field=field, use_text=use_text,
        country=country_filter, province=province_filter,
        geo_mode=geo_mode, lat=lat_str, lon=lon_str, radius=radius_str,
        sort_by=sort_by, # Pass sort selection back
        results=results, total=total,
        stats=country_stats,
        countries=countries, provinces=provinces
    )


# --- (Detail, Image, Comment, and Provinces routes remain unchanged) ---


@app.get("/wine/<id>")
def wine_details(id):
    coll = get_db()[COLLECTION_NAME]
    try: _id = ObjectId(id)
    except Exception: return "Invalid ID", 400
    wine = coll.find_one({"_id": _id})
    if not wine: return "Wine not found", 404
    wine["comments"] = wine.get("comments", [])
    return render_template("detail.html", wine=wine)


@app.get("/image/<id>")
def get_image(id):
    fs = get_fs()
    try:
        file_id = ObjectId(id)
        f = fs.get(file_id)
        filename = getattr(f, "filename", "default.png")
        mimetype = getattr(f, "content_type", None)
        if not mimetype and '.' in filename:
             ext = filename.rsplit('.', 1)[1].lower()
             if ext == 'png': mimetype = 'image/png'
             elif ext in ('jpg', 'jpeg'): mimetype = 'image/jpeg'
             elif ext == 'gif': mimetype = 'image/gif'
        mimetype = mimetype or 'application/octet-stream'
        headers = {'Cache-Control': 'public, max-age=604800'}
        return Response(f.read(), mimetype=mimetype, headers=headers)
    except (NoFile, Exception):
        try: return app.send_static_file("default.png")
        except: return "Image not found", 404


@app.post("/wine/<id>/comment")
def add_comment(id):
    coll = get_db()[COLLECTION_NAME]
    text = (request.form.get("text") or "").strip()[:2000]
    author = (request.form.get("author") or "anonymous").strip()[:120]
    if not text: return "Comment text is required", 400


    try: _id = ObjectId(id)
    except Exception: return "Invalid ID", 400


    comment = {
        "_id": ObjectId(), "text": text, "author": author or "anonymous",
        "createdAt": datetime.datetime.now(datetime.timezone.utc),
    }


    try:
        res = coll.update_one({"_id": _id}, {"$push": {"comments": comment}})
        if not res.matched_count: return "Wine not found", 404
    except Exception as e:
        print(f"Error adding comment to wine {_id}: {repr(e)}")
        return f"Error adding comment: {e}", 500


    return redirect(url_for("wine_details", id=id))


@app.get("/provinces")
def provinces_for_country():
    country = (request.args.get("country") or "").strip()
    coll = get_db()[COLLECTION_NAME]
    query = {"country": country} if country else {}
    provinces = sorted([p for p in coll.distinct("province", query) if p], key=str)[:300]
    return jsonify(provinces=provinces)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "3000"))
    debug_mode = os.getenv("FLASK_ENV") == "development" or True
    app.run(host="0.0.0.0", port=port, debug=debug_mode)

