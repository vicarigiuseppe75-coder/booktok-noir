"""BookTok Noir: paid content generator for Streamlit Community Cloud.

Payments are verified server-side with Stripe; credits are atomic in Supabase.
No secret belongs in this file or a public Git repository.
"""

import io
import hmac
import math
import random
import tempfile
from pathlib import Path

import imageio_ffmpeg
import numpy as np
import requests
import streamlit as st
import stripe
from PIL import Image, ImageDraw, ImageFont, ImageOps


st.set_page_config(page_title="BookTok Noir", page_icon="🕵️", layout="wide")

BOOK_TITLE = "Cronache del Macrocosmo"
BOOK_URL = "https://www.amazon.it/dp/B0HJ817GQ1"  # Verify your Italian edition URL.
PACK_CREDITS = 5
PACK_PRICE_CENTS = 299
PRESETS = {
    "Portale Chronos": (16, 216, 237),
    "Neon noir": (251, 72, 151),
    "Indagine notturna": (250, 181, 75),
}
EXAMPLES = [
    "Il messaggio porta la mia firma. Arriverà domani.",
    "Alle 03:17, la città ricorda un omicidio che non è ancora successo.",
    "Ho trovato la prova. Non ricordo più cosa dimostra.",
]


def setting(key):
    try:
        return str(st.secrets.get(key, "")).strip()
    except st.errors.StreamlitSecretNotFoundError:
        return ""


def configured():
    required = ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY",
                "STRIPE_SECRET_KEY", "APP_URL", "OWNER_EMAIL")
    return all(setting(key) for key in required)


def api(path, *, method="GET", payload=None, token=None, admin=False, params=None):
    """All Supabase calls happen on the Streamlit server."""
    key = setting("SUPABASE_SERVICE_KEY" if admin else "SUPABASE_ANON_KEY")
    headers = {"apikey": key, "Authorization": "Bearer " + (token or key),
               "Content-Type": "application/json"}
    response = requests.request(
        method, setting("SUPABASE_URL").rstrip("/") + path,
        headers=headers, json=payload, params=params, timeout=15,
    )
    if not response.ok:
        raise RuntimeError(response.json().get("msg", response.json().get(
            "error_description", response.json().get("message", "Richiesta non riuscita"))))
    return response.json() if response.content else None


def login(email, password):
    return api("/auth/v1/token", method="POST", params={"grant_type": "password"},
               payload={"email": email, "password": password})


def current_user():
    session = st.session_state.get("auth")
    if not session:
        return None
    try:
        return api("/auth/v1/user", token=session["access_token"])
    except Exception:
        try:
            fresh = api("/auth/v1/token", method="POST",
                        params={"grant_type": "refresh_token"},
                        payload={"refresh_token": session["refresh_token"]})
            st.session_state.auth = fresh
            return api("/auth/v1/user", token=fresh["access_token"])
        except Exception:
            st.session_state.pop("auth", None)
            return None


def is_owner(user):
    return bool(user and user.get("email", "").casefold() ==
                setting("OWNER_EMAIL").casefold())


def balance(user_id):
    rows = api("/rest/v1/wallets", admin=True,
               params={"user_id": "eq." + user_id, "select": "credits"})
    return rows[0]["credits"] if rows else 0


def redeem_checkout(session_id, user_id):
    """Verify Stripe payment, ownership, product and amount before granting."""
    stripe.api_key = setting("STRIPE_SECRET_KEY")
    payment = stripe.checkout.Session.retrieve(session_id)
    if (payment.payment_status != "paid" or payment.mode != "payment"
            or payment.metadata.get("user_id") != user_id
            or payment.metadata.get("product") != "booktok_noir_5"
            or payment.amount_total != PACK_PRICE_CENTS
            or payment.currency != "eur"):
        raise ValueError("Pagamento non verificato per questo account.")
    return api("/rest/v1/rpc/grant_purchase", method="POST", admin=True,
               payload={"p_user_id": user_id, "p_session_id": session_id,
                        "p_credits": PACK_CREDITS})


def create_checkout(user):
    stripe.api_key = setting("STRIPE_SECRET_KEY")
    base = setting("APP_URL").rstrip("/")
    payment = stripe.checkout.Session.create(
        mode="payment",
        customer_email=user["email"],
        line_items=[{"price_data": {
            "currency": "eur", "unit_amount": PACK_PRICE_CENTS,
            "product_data": {"name": "BookTok Noir · 5 creazioni"}},
            "quantity": 1}],
        metadata={"user_id": user["id"], "product": "booktok_noir_5"},
        success_url=base + "/?checkout={CHECKOUT_SESSION_ID}",
        cancel_url=base + "/?cancelled=1",
    )
    return payment.url


def font(size, bold=False):
    name = "DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"
    path = Path("/usr/share/fonts/truetype/dejavu") / name
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default()


def wrapped(draw, text, face, max_width):
    lines = []
    for paragraph in text.splitlines():
        line = ""
        for word in paragraph.split():
            candidate = (line + " " + word).strip()
            if draw.textbbox((0, 0), candidate, font=face)[2] <= max_width:
                line = candidate
            else:
                if line:
                    lines.append(line)
                line = word
        if line:
            lines.append(line)
    return lines or [""]


def uploaded_photo(file):
    """Decode a bounded user image; bytes stay in this session."""
    if file is None:
        return None
    if file.size > 12 * 1024 * 1024:
        raise ValueError("La foto deve pesare meno di 12 MB.")
    with Image.open(io.BytesIO(file.getvalue())) as source:
        if source.format not in ("JPEG", "PNG", "WEBP"):
            raise ValueError("Usa una foto JPG, PNG o WEBP.")
        source = ImageOps.exif_transpose(source)
        if source.width * source.height > 25_000_000:
            raise ValueError("La foto è troppo grande: riducila prima del caricamento.")
        source.thumbnail((1800, 3200))
        return source.convert("RGB").copy()


def frame(text, preset, seed, reveal=1, width=540, height=960, watermark=False,
          photo=None, motion=0):
    """Original procedural art; no copyrighted stock footage required."""
    rng = random.Random(seed)
    y_grid = np.linspace(0, 1, height, dtype=np.float32)[:, None, None]
    top = np.array([7, 11, 29], dtype=np.float32)
    bottom = np.array([25, 7, 34], dtype=np.float32)
    pixels = np.broadcast_to(top * (1-y_grid) + bottom*y_grid,
                             (height, width, 3)).copy().astype(np.uint8)
    image = Image.fromarray(pixels).convert("RGBA")
    if photo is not None:
        # Fill 9:16, then pan and zoom gently across the photograph.
        zoom = 1.08 + .08 * motion
        fitted = ImageOps.fit(photo, (int(width * zoom), int(height * zoom)),
                              method=Image.Resampling.LANCZOS)
        dx = int((fitted.width - width) * motion)
        dy = int((fitted.height - height) * (1 - motion))
        image = fitted.crop((dx, dy, dx + width, dy + height)).convert("RGBA")
        image.alpha_composite(Image.new("RGBA", (width, height), (3, 5, 18, 105)))
    draw = ImageDraw.Draw(image, "RGBA")
    accent = PRESETS[preset]
    cx, cy, r = int(width*.72), int(height*.25), int(width*.17)
    for i in range(4):
        rr = r+i*11
        draw.ellipse((cx-rr, cy-rr, cx+rr, cy+rr),
                     outline=(*accent, 180-i*38), width=3)
    for _ in range(60):
        x, y = rng.randrange(width), rng.randrange(int(height*.67))
        draw.ellipse((x, y, x+2, y+2), fill=(190, 230, 250, 110))
    if photo is None:
        skyline = int(height*.83)
        x = 0
        while x < width:
            bw = rng.randrange(20, 55)
            bh = rng.randrange(int(height*.1), int(height*.32))
            draw.rectangle((x, skyline-bh, x+bw, height), fill=(4, 7, 18, 255))
            for wx in range(x+7, x+bw-4, 12):
                for wy in range(skyline-bh+10, skyline-4, 18):
                    if rng.random() < .24:
                        draw.rectangle((wx, wy, wx+3, wy+6), fill=(*accent, 100))
            x += bw+rng.randrange(2, 8)
    for _ in range(65):
        x, y = rng.randrange(width), rng.randrange(height)
        draw.line((x, y, x-4, y+20), fill=(160, 210, 235, 40), width=1)
    draw.rounded_rectangle((int(width*.05), int(height*.34),
                            int(width*.95), int(height*.77)),
                           radius=18, fill=(2, 5, 15, 200))
    draw.text((int(width*.09), int(height*.37)), "DOSSIER / 09",
              font=font(max(13, width//29), True), fill=(*accent, 255))
    max_w = int(width*.81)
    for size in (width//13, width//15, width//17, width//20):
        face = font(size, True)
        lines = wrapped(draw, text, face, max_w)
        step = int(size*1.48)
        if len(lines)*step <= height*.34:
            break
    displayed = "\n".join(lines)[:math.ceil(len("\n".join(lines))*reveal)]
    y = int(height*.43)
    for line in displayed.split("\n"):
        draw.text((int(width*.09), y), line, font=face, fill=(237, 246, 251, 255))
        y += step
    draw.line((int(width*.09), int(height*.78), int(width*.91), int(height*.78)),
              fill=(*accent, 230), width=2)
    draw.text((int(width*.09), int(height*.80)), "OGNI INDIZIO HA UN PREZZO.",
              font=font(max(10, width//37)), fill=(210, 225, 240, 220))
    draw.text((int(width*.09), int(height*.88)), "CRONACHE DEL MACROCOSMO",
              font=font(max(10, width//33), True), fill=(*accent, 210))
    if watermark:
        draw.text((int(width*.1), int(height*.92)), "ANTEPRIMA · BOOKTOK NOIR",
                  font=font(max(12, width//27), True), fill=(*accent, 230))
    return image.convert("RGB")


def generate(text, preset, seed, photo=None):
    png = io.BytesIO()
    frame(text, preset, seed, photo=photo).save(png, format="PNG")
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "booktok_noir.mp4")
        writer = imageio_ffmpeg.write_frames(
            path, (360, 640), fps=8, codec="libx264",
            pix_fmt_in="rgb24", pix_fmt_out="yuv420p",
            macro_block_size=8,
            output_params=["-movflags", "+faststart"],
        )
        writer.send(None)
        try:
            for i in range(32):
                picture = frame(text, preset, seed, reveal=min(1, i/20),
                                width=360, height=640, photo=photo, motion=i/31)
                writer.send(np.asarray(picture, dtype=np.uint8).tobytes())
        finally:
            writer.close()
        video = Path(path).read_bytes()
    return png.getvalue(), video


def caption(text):
    snippet = " ".join(text.split())[:115].rstrip()
    return (f"Un indizio che non avrei dovuto trovare.\n\n«{snippet}»\n\n"
            "Tu cosa faresti? Dimmelo nei commenti.\n\n"
            "#booktokitalia #thrillerscifi #thrilleritaliano "
            "#fantascienza #libriconsigliati #libridigitali")


st.markdown("""
<style>
.stApp {background: radial-gradient(circle at 75% 0%, #242441, #090d19 55%);}
.hero {padding:18px 22px; border:1px solid #2cdae5; border-radius:16px;
       background:#10182b; margin-bottom:20px;}
.hero a {color:#78eef5 !important; font-weight:700;}
</style>
""", unsafe_allow_html=True)
st.title("🕵️ BookTok Noir")
st.write("Trasforma un indizio in un video verticale, un poster e una didascalia pronti per BookTok.")
st.markdown(f'<div class="hero">Vuoi leggere un vero thriller sci-fi noir? '
            f'Scopri <b>{BOOK_TITLE}</b> su '
            f'<a href="{BOOK_URL}" target="_blank" rel="noopener noreferrer">Amazon</a>.</div>',
            unsafe_allow_html=True)

if not configured():
    st.info("Anteprima pubblica. La creazione è riservata al proprietario finché i pagamenti non sono attivi.")

st.subheader("Esempi creati con l'app")
columns = st.columns(3)
for i, (column, example) in enumerate(zip(columns, EXAMPLES)):
    with column:
        st.image(frame(example, list(PRESETS)[i], i+42, watermark=True),
                 width="stretch")

if not configured():
    owner_password = setting("OWNER_PASSWORD")
    if not owner_password:
        st.info("Generatore non ancora attivo: il proprietario deve aggiungere OWNER_PASSWORD nelle impostazioni riservate dell'app.")
        st.stop()
    if not st.session_state.get("owner_unlocked"):
        with st.form("owner_access"):
            entered_password = st.text_input("Accesso autore", type="password")
            enter = st.form_submit_button("Entra")
        if enter:
            if hmac.compare_digest(entered_password, owner_password):
                st.session_state.owner_unlocked = True
                st.rerun()
            else:
                st.error("Password non corretta.")
        st.stop()
    st.success("Accesso autore: creazioni gratuite.")
    if st.button("Esci dall'accesso autore"):
        st.session_state.owner_unlocked = False
        st.session_state.pop("result", None)
        st.rerun()
    with st.form("owner_generator"):
        owner_text = st.text_area("Citazione, indizio o colpo di scena", max_chars=210,
                                  placeholder="Il messaggio porta la mia firma. Arriverà domani.")
        owner_preset = st.selectbox("Atmosfera", list(PRESETS))
        owner_file = st.file_uploader("Tua foto (facoltativa): JPG, PNG o WEBP",
                                      type=["jpg", "jpeg", "png", "webp"], key="owner_photo")
        owner_submit = st.form_submit_button("Genera poster + video", type="primary")
    if owner_submit:
        if len(owner_text.strip()) < 8:
            st.warning("Scrivi almeno 8 caratteri.")
        else:
            with st.spinner("Creo il tuo contenuto..."):
                try:
                    png, mp4 = generate(owner_text.strip(), owner_preset,
                                        random.SystemRandom().randrange(10**9),
                                        uploaded_photo(owner_file))
                    st.session_state.owner_result = {"png": png, "mp4": mp4,
                                                     "caption": caption(owner_text.strip())}
                except Exception:
                    st.error("Creazione non riuscita. Riprova più tardi.")
    owner_result = st.session_state.get("owner_result")
    if owner_result:
        st.subheader("Pronto da pubblicare")
        st.image(owner_result["png"], width=360)
        st.video(owner_result["mp4"])
        a, b = st.columns(2)
        a.download_button("Scarica poster PNG", owner_result["png"], "booktok_noir.png", "image/png")
        b.download_button("Scarica video MP4", owner_result["mp4"], "booktok_noir.mp4", "video/mp4")
        st.write("**Didascalia da copiare:**")
        st.code(owner_result["caption"], language=None)
    st.stop()

user = current_user()
if user is None:
    st.subheader("Accedi per creare")
    left, right = st.columns(2)
    with left:
        with st.form("login"):
            email = st.text_input("Email", key="login_email")
            password = st.text_input("Password", type="password", key="login_password")
            submitted = st.form_submit_button("Accedi")
        if submitted:
            try:
                st.session_state.auth = login(email.strip(), password)
                st.rerun()
            except Exception:
                st.error("Accesso non riuscito. Controlla email, password e conferma dell'account.")
    with right:
        with st.form("signup"):
            new_email = st.text_input("Nuova email")
            new_password = st.text_input("Crea password", type="password")
            register = st.form_submit_button("Registrati")
        if register:
            if len(new_password) < 8:
                st.warning("Usa una password di almeno 8 caratteri.")
            else:
                try:
                    api("/auth/v1/signup", method="POST",
                        payload={"email": new_email.strip(), "password": new_password})
                    st.success("Registrazione inviata. Conferma l'email, poi accedi.")
                except Exception:
                    st.error("Registrazione non riuscita. Riprova o usa un'altra email.")
    st.stop()

owner = is_owner(user)
st.write(f"Connesso come **{user['email']}**" + (" · accesso autore" if owner else ""))
if st.button("Esci"):
    st.session_state.pop("auth", None)
    st.session_state.pop("result", None)
    st.rerun()

checkout_id = st.query_params.get("checkout")
if checkout_id:
    try:
        awarded = redeem_checkout(checkout_id, user["id"])
        st.success("Pagamento verificato: 5 crediti accreditati." if awarded
                   else "Pagamento già accreditato in precedenza.")
        st.query_params.clear()
    except Exception:
        st.warning("Pagamento non ancora verificato per questo account. Puoi riprovare qui sotto con l'ID della sessione Checkout.")

if not owner:
    try:
        credits = balance(user["id"])
    except Exception:
        st.error("Crediti temporaneamente non disponibili. Riprova più tardi.")
        st.stop()
    st.metric("Creazioni disponibili", credits)
    try:
        checkout_url = create_checkout(user)
        st.link_button("Acquista 5 creazioni · 2,99 €", checkout_url, type="primary")
    except Exception:
        st.error("Checkout temporaneamente non disponibile.")
    with st.expander("Hai pagato ma non vedi i crediti?"):
        recovery = st.text_input("ID della sessione Stripe (inizia con cs_)")
        if st.button("Verifica acquisto") and recovery.startswith("cs_"):
            try:
                redeem_checkout(recovery, user["id"])
                st.success("Acquisto verificato. Aggiorna la pagina.")
            except Exception:
                st.error("Impossibile verificare questo pagamento per il tuo account.")
else:
    credits = 1
    st.success("Accesso autore: creazioni senza addebito.")

if credits <= 0:
    st.info("Acquista un pacchetto per creare e scaricare contenuti.")
    st.stop()

st.subheader("Crea il tuo contenuto")
with st.form("generator"):
    text = st.text_area("Citazione, indizio o colpo di scena (max 210 caratteri)",
                        max_chars=210, height=125,
                        placeholder="Il messaggio porta la mia firma. Arriverà domani.")
    preset = st.selectbox("Atmosfera", list(PRESETS))
    photo_file = st.file_uploader("Tua foto (facoltativa): JPG, PNG o WEBP",
                                  type=["jpg", "jpeg", "png", "webp"], key="customer_photo")
    submit = st.form_submit_button("Genera poster + video", type="primary")

if submit:
    cleaned = text.strip()
    if len(cleaned) < 8:
        st.warning("Scrivi almeno 8 caratteri.")
    else:
        with st.spinner("Sto preparando il tuo contenuto..."):
            try:
                png, mp4 = generate(cleaned, preset, random.SystemRandom().randrange(10**9),
                                    uploaded_photo(photo_file))
                if not owner:
                    remaining = api("/rest/v1/rpc/spend_credit", method="POST", admin=True,
                                    payload={"p_user_id": user["id"]})
                    if remaining is None or remaining < 0:
                        raise ValueError("Crediti esauriti. Ricarica la pagina.")
                st.session_state.result = {"png": png, "mp4": mp4,
                                           "caption": caption(cleaned), "user": user["id"]}
                st.rerun()
            except Exception:
                st.error("Creazione non riuscita. Nessun credito è stato scalato se i file non erano pronti. Se il problema persiste, contatta l'autore.")

result = st.session_state.get("result")
if result and result["user"] == user["id"]:
    st.subheader("Pronto da pubblicare")
    st.image(result["png"], width=360)
    st.video(result["mp4"])
    a, b = st.columns(2)
    a.download_button("Scarica poster PNG", result["png"], "booktok_noir.png", "image/png")
    b.download_button("Scarica video MP4", result["mp4"], "booktok_noir.mp4", "video/mp4")
    st.write("**Didascalia: usa il pulsante Copia nel riquadro.**")
    st.code(result["caption"], language=None)
