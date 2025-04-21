from flask import Flask, render_template, g, request, redirect, url_for, send_file
import sqlite3
import io
import os
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# ---------------------------
# SQLite 設定
# ---------------------------
DATABASE = os.environ.get("DB_PATH", "/var/data/coffee_inventory_app.db")

app = Flask(__name__)

# ---------------------------------------
# DB ユーティリティ
# ---------------------------------------

def get_db():
    """スレッド毎に 1 つだけ SQLite 接続を保持"""
    db = getattr(g, "_database", None)
    if db is None:
        os.makedirs(os.path.dirname(DATABASE), exist_ok=True)
        db = g._database = sqlite3.connect(DATABASE, detect_types=sqlite3.PARSE_DECLTYPES)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()

# ---------------------------------------
# 初回起動時にテーブル・ダミーデータを自動生成
# ---------------------------------------

SCHEMA_FILE = os.path.join(app.root_path, "schema.sql")

def init_db():
    db = get_db()
    with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
        db.executescript(f.read())
    db.commit()
    add_dummy_products()  # スキーマ作成直後にダミーデータ投入

@app.before_request
def ensure_tables():
    """最初のリクエストでテーブルが無ければ schema.sql + ダミーデータ"""
    db = get_db()
    try:
        db.execute("SELECT 1 FROM InventoryItem LIMIT 1")
    except sqlite3.OperationalError:
        init_db()

# ---------------------------------------
# ルーティング
# ---------------------------------------

@app.route("/")
def root():
    return redirect(url_for("home"))

@app.route("/home")
def home():
    return render_template("home.html")

@app.route("/product_list")
def product_list():
    db = get_db()
    cur = db.execute('''
        SELECT InventoryItem.name, InventoryItem.price, InventoryItem.order_unit, Supplier.name AS supplier_name
        FROM InventoryItem
        LEFT JOIN Supplier ON InventoryItem.id % 3 + 1 = Supplier.id
    ''')
    products = cur.fetchall()
    return render_template("product_list.html", products=products)

# -------------------------
# ダミーデータ投入関数
# -------------------------

def add_dummy_products():
    """テーブル作成直後に 1 回だけ呼び出し"""
    db = get_db()
    # すでにデータがあればスキップ
    if db.execute("SELECT COUNT(*) FROM InventoryItem").fetchone()[0] > 0:
        return
    # 仕入先
    suppliers = [
        ("コーヒー商事", "熊本県熊本市中央区1-1", "999-999-9999", "kumamotocafe@kuma.com", "info@coffee.com"),
        ("紅茶トレード", "東京都新宿区2-2", "888-888-8888", "tokyo@tea.com", "info@tea.com"),
        ("スイーツ流通", "大阪府大阪市北区3-3", "777-777-7777", "osaka@sweets.com", "info@sweets.com")
    ]
    for name, address, phone, email, contact in suppliers:
        db.execute(
            "INSERT INTO Supplier (name, address, phone, email, contact_info) VALUES (?, ?, ?, ?, ?)",
            (name, address, phone, email, contact)
        )
    # 商品
    products = [
        ("ブレンドコーヒー", 450, "200g"),
        ("アールグレイティー", 400, "100g"),
        ("チーズケーキ", 480, "1ホール"),
        ("カフェラテ", 500, "10杯分"),
        ("抹茶ラテ", 520, "10杯分"),
        ("ショコラケーキ", 530, "1ホール")
    ]
    for i, (name, price, order_unit) in enumerate(products, start=1):
        db.execute(
            "INSERT INTO InventoryItem (name, quantity, price, order_unit) VALUES (?, ?, ?, ?)",
            (name, 10 + i, price, order_unit)
        )
    db.commit()

@app.route('/add_item', methods=['GET', 'POST'])
def add_item():
    if request.method == 'POST':
        name = request.form['name']
        quantity = int(request.form['quantity'])
        price = float(request.form['price'])
        order_unit = request.form.get('order_unit', '')

        db = get_db()
        db.execute(
            'INSERT INTO InventoryItem (name, quantity, price, order_unit) VALUES (?, ?, ?, ?)',
            (name, quantity, price, order_unit)
        )
        db.commit()
        return redirect(url_for('show_inventory'))
    
    return render_template('add_item.html')


@app.route('/edit_item/<int:item_id>', methods=['GET', 'POST'])
def edit_item(item_id):
    db = get_db()
    if request.method == 'POST':
        name = request.form['name']
        quantity = int(request.form['quantity'])
        price = float(request.form['price'])

        db.execute(
            'UPDATE InventoryItem SET name = ?, quantity = ?, price = ? WHERE id = ?',
            (name, quantity, price, item_id)
        )
        db.commit()
        return redirect(url_for('index'))

    cur = db.execute('SELECT * FROM InventoryItem WHERE id = ?', (item_id,))
    item = cur.fetchone()
    return render_template('edit_item.html', item=item)

@app.route('/index')
def show_inventory():
    db = get_db()
    cur = db.execute('SELECT * FROM InventoryItem')
    items = cur.fetchall()
    # 入荷待ち一覧も取得
    incoming = db.execute('''
        SELECT OrderItem.*, InventoryItem.name as item_name
        FROM OrderItem
        JOIN InventoryItem ON OrderItem.inventory_item_id = InventoryItem.id
        WHERE OrderItem.is_received = 0
    ''').fetchall()
    return render_template('index.html', items=items, incoming=incoming)

@app.route('/receive_item/<int:order_item_id>', methods=['POST'])
def receive_item(order_item_id):
    db = get_db()
    # 入荷待ちOrderItem取得
    order_item = db.execute('SELECT * FROM OrderItem WHERE id = ?', (order_item_id,)).fetchone()
    if order_item and order_item['is_received'] == 0:
        # 在庫数加算
        db.execute('UPDATE InventoryItem SET quantity = quantity + ? WHERE id = ?', (order_item['quantity_ordered'], order_item['inventory_item_id']))
        # 入荷済みに更新
        db.execute('UPDATE OrderItem SET is_received = 1, received_date = ? WHERE id = ?', (datetime.now(), order_item_id))
        # 履歴追加
        db.execute('INSERT INTO InventoryHistory (inventory_item_id, quantity_change, change_reason) VALUES (?, ?, ?)', (order_item['inventory_item_id'], order_item['quantity_ordered'], '入荷'))
        db.commit()
    return redirect(url_for('show_inventory'))

@app.route('/suppliers')
def show_suppliers():
    db = get_db()
    cur = db.execute('SELECT * FROM Supplier')
    suppliers = cur.fetchall()
    return render_template('suppliers.html', suppliers=suppliers)

@app.route('/purchase_orders')
def show_purchase_orders():
    db = get_db()
    cur = db.execute('SELECT * FROM PurchaseOrder')
    purchase_orders = cur.fetchall()
    # 各発注ごとに商品明細を取得
    orders = []
    for order in purchase_orders:
        items = db.execute('''
            SELECT OrderItem.*, InventoryItem.name 
            FROM OrderItem 
            JOIN InventoryItem ON OrderItem.inventory_item_id = InventoryItem.id 
            WHERE OrderItem.purchase_order_id = ?
        ''', (order['id'],)).fetchall()
        orders.append({
            **dict(order),
            'items': [dict(item) for item in items]
        })
    return render_template('purchase_orders.html', purchase_orders=orders)

@app.route('/create_order', methods=['GET', 'POST'])
def create_order():
    db = get_db()
    if request.method == 'POST':
        # 入力値取得
        order_date = request.form['order_date']
        supplier_id = int(request.form['supplier_id'])
        item_ids = request.form.getlist('item_id[]')
        prices = request.form.getlist('price[]')
        quantities = request.form.getlist('quantity[]')
        subtotals = request.form.getlist('subtotal[]')
        order_total = float(request.form.get('order_total', 0))
        # 発注履歴保存
        cur = db.execute('INSERT INTO PurchaseOrder (supplier_id, order_date, total_amount) VALUES (?, ?, ?)', (supplier_id, order_date, order_total))
        purchase_order_id = cur.lastrowid
        order_items = []
        for item_id, price, quantity, subtotal in zip(item_ids, prices, quantities, subtotals):
            db.execute('INSERT INTO OrderItem (purchase_order_id, inventory_item_id, quantity_ordered, unit_price) VALUES (?, ?, ?, ?)', (purchase_order_id, int(item_id), int(quantity), float(price)))
            item = db.execute('SELECT * FROM InventoryItem WHERE id = ?', (item_id,)).fetchone()
            order_items.append({
                'name': item['name'],
                'price': float(price),
                'quantity': int(quantity),
                'subtotal': float(subtotal)
            })
        db.commit()
        # 仕入れ先情報取得
        supplier = db.execute('SELECT * FROM Supplier WHERE id = ?', (supplier_id,)).fetchone()
        # 発注元情報
        origin = {
            'name': '熊本珈琲',
            'address': '熊本県八代市１−１',
            'tel': '999-999-9999',
            'email': 'kumamotocafe@kuma.com'
        }
        # PDF生成（日本語対応フォント指定）
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfbase import pdfmetrics
        pdfmetrics.registerFont(UnicodeCIDFont('HeiseiKakuGo-W5'))
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        c.setFont('HeiseiKakuGo-W5', 16)
        c.drawString(50, 800, '発注書')
        c.setFont('HeiseiKakuGo-W5', 10)
        c.drawString(400, 800, f'発注日時: {order_date}')

        # 仕入れ先情報（左上）
        y = 770
        c.setFont('HeiseiKakuGo-W5', 12)
        c.drawString(50, y, supplier["name"])
        y -= 18
        c.setFont('HeiseiKakuGo-W5', 10)
        c.drawString(50, y, f'連絡先: {supplier["contact_info"]}')
        y -= 15
        c.drawString(50, y, f'住所: {supplier["address"]}')
        y -= 15
        c.drawString(50, y, f'電話番号: {supplier["phone"]}')
        y -= 15
        c.drawString(50, y, f'メールアドレス: {supplier["email"]}')

        # 商品明細（複数行対応）
        y -= 25
        c.setFont('HeiseiKakuGo-W5', 11)
        c.drawString(50, y, '商品明細:')
        y -= 18
        c.setFont('HeiseiKakuGo-W5', 10)
        c.drawString(60, y, '商品名')
        c.drawString(180, y, '単価')
        c.drawString(250, y, '個数')
        c.drawString(320, y, '小計')
        y -= 15
        for oi in order_items:
            c.drawString(60, y, oi['name'])
            c.drawString(180, y, f"{oi['price']:.0f} 円")
            c.drawString(250, y, str(oi['quantity']))
            c.drawString(320, y, f"{oi['subtotal']:.0f} 円")
            y -= 15
        # 合計金額
        y -= 10
        c.setFont('HeiseiKakuGo-W5', 11)
        c.drawString(250, y, '合計金額:')
        c.setFont('HeiseiKakuGo-W5', 11)
        c.drawString(320, y, f'{order_total:.0f} 円')

        # 発注元情報（右下）
        base_x = 545  # A4横幅595pt, 右端から50pt余白
        base_y = 120
        c.setFont('HeiseiKakuGo-W5', 11)
        c.drawRightString(base_x, base_y + 60, f'発注元: {origin["name"]}')
        c.setFont('HeiseiKakuGo-W5', 10)
        c.drawRightString(base_x, base_y + 45, f'住所: {origin["address"]}')
        c.drawRightString(base_x, base_y + 30, f'電話番号: {origin["tel"]}')
        c.drawRightString(base_x, base_y + 15, f'メール: {origin["email"]}')

        c.showPage()
        c.save()
        buf.seek(0)
        return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name='order.pdf')
    # GET時: フォーム表示
    suppliers = db.execute('SELECT * FROM Supplier').fetchall()
    items = db.execute('SELECT * FROM InventoryItem').fetchall()
    now = datetime.now().strftime('%Y-%m-%dT%H:%M')
    return render_template('create_order.html', suppliers=suppliers, items=items, now=now)

@app.route('/order_items')
def show_order_items():
    db = get_db()
    cur = db.execute('SELECT * FROM OrderItem')
    order_items = cur.fetchall()
    return render_template('order_items.html', order_items=order_items)

@app.route('/inventory_history')
def show_inventory_history():
    db = get_db()
    cur = db.execute('SELECT * FROM InventoryHistory')
    inventory_history = cur.fetchall()
    return render_template('inventory_history.html', inventory_history=inventory_history)

def init_db():
    with app.app_context():
        db = get_db()
        with open('schema.sql', 'r') as f:
            db.executescript(f.read())
        db.commit()

@app.route('/change_stock/<int:item_id>', methods=['GET', 'POST'])
def change_stock(item_id):
    db = get_db()
    if request.method == 'POST':
        quantity_change = float(request.form['quantity_change'])
        change_reason = request.form['change_reason']

        # 在庫数を更新
        db.execute(
            'UPDATE InventoryItem SET quantity = quantity + ? WHERE id = ?',
            (quantity_change, item_id)
        )
        # 履歴を追加
        db.execute(
            'INSERT INTO InventoryHistory (inventory_item_id, quantity_change, change_reason) VALUES (?, ?, ?)',
            (item_id, quantity_change, change_reason)
        )
        db.commit()
        return redirect(url_for('show_inventory'))

    cur = db.execute('SELECT * FROM InventoryItem WHERE id = ?', (item_id,))
    item = cur.fetchone()
    return render_template('change_stock.html', item=item)

@app.route('/edit_supplier/<int:supplier_id>', methods=['GET', 'POST'])
def edit_supplier(supplier_id):
    db = get_db()
    if request.method == 'POST':
        name = request.form['name']
        address = request.form['address']
        phone = request.form['phone']
        email = request.form['email']
        contact_info = request.form['contact_info']
        db.execute(
            'UPDATE Supplier SET name = ?, address = ?, phone = ?, email = ?, contact_info = ? WHERE id = ?',
            (name, address, phone, email, contact_info, supplier_id)
        )
        db.commit()
        return redirect(url_for('show_suppliers'))
    cur = db.execute('SELECT * FROM Supplier WHERE id = ?', (supplier_id,))
    supplier = cur.fetchone()
    return render_template('edit_supplier.html', supplier=supplier)

@app.route('/add_supplier', methods=['GET', 'POST'])
def add_supplier():
    db = get_db()
    if request.method == 'POST':
        name = request.form['name']
        address = request.form['address']
        phone = request.form['phone']
        email = request.form['email']
        contact_info = request.form['contact_info']
        db.execute(
            'INSERT INTO Supplier (name, address, phone, email, contact_info) VALUES (?, ?, ?, ?, ?)',
            (name, address, phone, email, contact_info)
        )
        db.commit()
        return redirect(url_for('show_suppliers'))
    return render_template('add_supplier.html')

@app.route('/delete_supplier/<int:supplier_id>', methods=['POST'])
def delete_supplier(supplier_id):
    db = get_db()
    db.execute('DELETE FROM Supplier WHERE id = ?', (supplier_id,))
    db.commit()
    return redirect(url_for('show_suppliers'))

# --- 本番環境でも必ずDBとダミーデータを初期化 ---
with app.app_context():
    try:
        db = get_db()
        db.execute("SELECT 1 FROM InventoryItem LIMIT 1")
    except Exception:
        init_db()

if __name__ == "__main__":
    if not os.path.exists(DATABASE):
        with app.app_context():
            init_db()
    app.run(debug=True)