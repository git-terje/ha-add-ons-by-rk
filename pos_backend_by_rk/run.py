import os, json, datetime, io
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, Request, HTTPException, Query, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
import uvicorn, requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
import qrcode
from PIL import Image, ImageDraw, ImageFont

APP_PORT = int(os.getenv("PORT", "8091"))
HA_URL = "http://supervisor/core/api"
HA_TOKEN = os.environ.get("SUPERVISOR_TOKEN")

def read_options() -> Dict[str, Any]:
    with open("/data/options.json", "r", encoding="utf-8") as f:
        return json.load(f)

def get_creds(sa_path: str):
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    return service_account.Credentials.from_service_account_file(sa_path, scopes=scopes)

def get_service(creds):
    return build("sheets", "v4", credentials=creds, cache_discovery=False)

def read_tab(service, sheet_id: str, tab: str) -> List[List[Any]]:
    res = service.spreadsheets().values().get(spreadsheetId=sheet_id, range=f"{tab}!A:Z").execute()
    return res.get("values", [])

def to_dicts(rows: List[List[Any]]) -> List[Dict[str, Any]]:
    if not rows:
        return []
    headers = rows[0]
    return [{h: (r[i] if i < len(r) else "") for i, h in enumerate(headers)} for r in rows[1:]]

def lookup_user(service, sheet_id: str, user_id: Optional[str]) -> Dict[str, Any]:
    if not user_id:
        return {}
    for u in to_dicts(read_tab(service, sheet_id, "Users")):
        if u.get("user_id") == user_id:
            return u
    return {}

def lookup_product(service, sheet_id: str, product_id: Optional[str]=None, short_id: Optional[str]=None) -> Dict[str, Any]:
    for p in to_dicts(read_tab(service, sheet_id, "Products")):
        if product_id and p.get("product_id") == product_id:
            return p
        if short_id and p.get("short_id") == short_id:
            return p
    return {}

def lookup_reseller_price(service, sheet_id: str, reseller_id: str, product_id: str, on_date: Optional[datetime.date]=None) -> Dict[str, Any]:
    rows = to_dicts(read_tab(service, sheet_id, "ResellerPricing"))
    if on_date is None:
        on_date = datetime.date.today()
    best = {}
    for r in rows:
        if r.get("reseller_id") != reseller_id or r.get("product_id") != product_id:
            continue
        vf = r.get("valid_from","")
        vt = r.get("valid_to","")
        try:
            vf_date = datetime.date.fromisoformat(vf) if vf else datetime.date(1970,1,1)
        except: vf_date = datetime.date(1970,1,1)
        try:
            vt_date = datetime.date.fromisoformat(vt) if vt else datetime.date(9999,12,31)
        except: vt_date = datetime.date(9999,12,31)
        if vf_date <= on_date <= vt_date:
            if not best or vf_date >= datetime.date.fromisoformat(best.get("valid_from","1970-01-01")):
                best = r
    return best

def update_row(service, sheet_id: str, tab: str, row_idx: int, headers: List[str], row_values: List[Any]):
    end_col = chr(ord("A") + len(headers) - 1)
    range_ref = f"{tab}!A{row_idx}:{end_col}{row_idx}"
    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=range_ref,
        valueInputOption="RAW",
        body={"values": [row_values]}
    ).execute()

def fire_event(event_name: str, payload: Dict[str, Any]):
    if not HA_TOKEN:
        return
    url = f"{HA_URL}/events/{event_name}"
    headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
    try: requests.post(url, headers=headers, data=json.dumps(payload), timeout=5)
    except Exception: pass

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/ui", StaticFiles(directory="static", html=True), name="ui")
app.mount("/pos", StaticFiles(directory="static", html=True), name="pos")

@app.get("/")
def root_redirect():
    return RedirectResponse(url="/pos/", status_code=307)

@app.get("/health")
def health():
    return {"status": "ok", "port": APP_PORT}

@app.get("/pos/users")
def get_users():
    o = read_options(); s = get_service(get_creds(o["service_account_json"]))
    return to_dicts(read_tab(s, o["google_sheet_id"], "Users"))

@app.get("/pos/customers")
def get_customers():
    o = read_options(); s = get_service(get_creds(o["service_account_json"]))
    return to_dicts(read_tab(s, o["google_sheet_id"], "Customers"))

@app.get("/pos/stock")
def get_stock(reseller_id: str = Query(None), user_id: str = Query(None)):
    o = read_options(); s = get_service(get_creds(o["service_account_json"]))
    items = to_dicts(read_tab(s, o["google_sheet_id"], "Stock"))
    if user_id:
        u = lookup_user(s, o["google_sheet_id"], user_id); rid = u.get("user_id") if u else None
        if rid: items = [x for x in items if x.get("reseller_id") == rid]
    elif reseller_id:
        items = [x for x in items if x.get("reseller_id") == reseller_id]
    return items

@app.post("/pos/sale")
async def pos_sale(req: Request):
    p = await req.json()
    user_id = p.get("user_id",""); reseller_id = p.get("reseller_id","")
    product_id = p.get("product_id"); short_id = p.get("short_id")
    qty = int(p.get("qty",1)); customer_id = p.get("customer_id","C-000")
    payment_method = p.get("payment_method","cash")
    if not product_id and not short_id:
        raise HTTPException(status_code=400, detail="product_id or short_id required")
    o = read_options(); s = get_service(get_creds(o["service_account_json"]))
    u = lookup_user(s, o["google_sheet_id"], user_id); person_entity_id = u.get("person_entity_id","") if u else ""
    prod = lookup_product(s, o["google_sheet_id"], product_id, short_id)
    if not prod: raise HTTPException(status_code=404, detail="Product not found")
    product_id = prod.get("product_id"); short_id = prod.get("short_id")
    rp = lookup_reseller_price(s, o["google_sheet_id"], reseller_id, product_id)
    try: price = float(rp.get("price") or prod.get("base_price") or 0)
    except: price = float(prod.get("base_price") or 0)
    try: commission_pct = float(rp.get("commission_pct") or 0)
    except: commission_pct = 0.0
    total = price * qty
    sale_row = [datetime.datetime.now().isoformat(), user_id, person_entity_id, customer_id, product_id, short_id, qty, price, commission_pct, total, payment_method]
    s.spreadsheets().values().append(spreadsheetId=o["google_sheet_id"], range="Sales!A:Z", valueInputOption="RAW", body={"values": [sale_row]}).execute()
    stock_rows = read_tab(s, o["google_sheet_id"], "Stock")
    if stock_rows:
        hdr = stock_rows[0]
        try:
            pid_idx, rid_idx, qty_idx = hdr.index("product_id"), hdr.index("reseller_id"), hdr.index("reseller_qty")
            if reseller_id:
                for i, r in enumerate(stock_rows[1:], start=2):
                    pid = r[pid_idx] if len(r) > pid_idx else ""; rid = r[rid_idx] if len(r) > rid_idx else ""
                    if str(pid) == str(product_id) and str(rid) == str(reseller_id):
                        cur = float(r[qty_idx]) if len(r) > qty_idx and r[qty_idx] != "" else 0.0
                        r_out = r[:] + [""] * (len(hdr) - len(r)); r_out[qty_idx] = cur - qty
                        update_row(s, o["google_sheet_id"], "Stock", i, hdr, r_out); break
        except ValueError: pass
    fire_event(o.get("ha_event","pos_sale"), {"user_id":user_id,"reseller_id":reseller_id,"customer_id":customer_id,"total":total,"product_id":product_id,"qty":qty})
    return {"status":"ok","total":total,"customer_id":customer_id,"payment_method":payment_method,"price":price,"commission_pct":commission_pct}

@app.post("/pos/checkout")
async def checkout(req: Request):
    p = await req.json()
    items = p.get("items", [])
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=400, detail="No items")
    user_id = p.get("user_id",""); reseller_id = p.get("reseller_id","")
    customer_id = p.get("customer_id","C-000"); payment_method = p.get("payment_method","cash")
    o = read_options(); s = get_service(get_creds(o["service_account_json"]))
    u = lookup_user(s, o["google_sheet_id"], user_id); person_entity_id = u.get("person_entity_id","") if u else ""
    grand_total, written = 0.0, 0
    for it in items:
        prod = lookup_product(s, o["google_sheet_id"], it.get("product_id"), it.get("short_id"))
        if not prod: raise HTTPException(status_code=404, detail=f"Product not found: {it}")
        product_id = prod.get("product_id"); short_id = prod.get("short_id")
        qty = int(it.get("qty",1))
        rp = lookup_reseller_price(s, o["google_sheet_id"], reseller_id, product_id)
        try: price = float(rp.get("price") or prod.get("base_price") or 0)
        except: price = float(prod.get("base_price") or 0)
        try: commission_pct = float(rp.get("commission_pct") or 0)
        except: commission_pct = 0.0
        total = price * qty; grand_total += total
        row = [datetime.datetime.now().isoformat(), user_id, person_entity_id, customer_id, product_id, short_id, qty, price, commission_pct, total, payment_method]
        s.spreadsheets().values().append(spreadsheetId=o["google_sheet_id"], range="Sales!A:Z", valueInputOption="RAW", body={"values": [row]}).execute(); written += 1
        stock_rows = read_tab(s, o["google_sheet_id"], "Stock")
        if stock_rows:
            hdr = stock_rows[0]
            try:
                pid_idx, rid_idx, qty_idx = hdr.index("product_id"), hdr.index("reseller_id"), hdr.index("reseller_qty")
                if reseller_id:
                    for i, r in enumerate(stock_rows[1:], start=2):
                        pid = r[pid_idx] if len(r) > pid_idx else ""; rid = r[rid_idx] if len(r) > rid_idx else ""
                        if str(pid) == str(product_id) and str(rid) == str(reseller_id):
                            cur = float(r[qty_idx]) if len(r) > qty_idx and r[qty_idx] != "" else 0.0
                            r_out = r[:] + [""] * (len(hdr) - len(r)); r_out[qty_idx] = cur - qty
                            update_row(s, o["google_sheet_id"], "Stock", i, hdr, r_out); break
            except ValueError: pass
    fire_event(o.get("ha_event","pos_sale"), {"user_id":user_id,"reseller_id":reseller_id,"customer_id":customer_id,"total":grand_total,"items":items})
    return {"status":"ok","total":grand_total,"lines":written,"customer_id":customer_id,"payment_method":payment_method}

@app.get("/pos/label/{product_id}")
def generate_label(product_id: str):
    o = read_options(); s = get_service(get_creds(o["service_account_json"]))
    products = to_dicts(read_tab(s, o["google_sheet_id"], "Products"))
    prod = next((p for p in products if p.get("product_id") == product_id), None)
    if not prod: raise HTTPException(status_code=404, detail="Product not found")
    label_text = (
        f"{prod.get('short_id','')} - {prod.get('name','')}\n"
        f"Size: {prod.get('package_size','')}\n"
        f"Price: {prod.get('base_price','')} NOK\n"
        f"Producer: {prod.get('producer','')}"
    )
    qr = qrcode.QRCode(box_size=4, border=2); qr.add_data(json.dumps({"product_id": prod.get("product_id"), "short_id": prod.get("short_id")})); qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    img = Image.new("RGB", (400, 300), "white"); draw = ImageDraw.Draw(img)
    try: font = ImageFont.load_default()
    except: font = None
    draw.text((10, 10), label_text, fill="black", font=font); img.paste(qr_img, (250, 50))
    buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
    return Response(content=buf.getvalue(), media_type="image/png")

if __name__ == "__main__":
    uvicorn.run("run:app", host="0.0.0.0", port=APP_PORT)
