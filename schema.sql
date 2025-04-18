DROP TABLE IF EXISTS InventoryItem;
CREATE TABLE IF NOT EXISTS InventoryItem (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    order_unit TEXT
);

DROP TABLE IF EXISTS Supplier;
CREATE TABLE Supplier (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    address TEXT,
    phone TEXT,
    email TEXT,
    contact_info TEXT
);

DROP TABLE IF EXISTS PurchaseOrder;
CREATE TABLE PurchaseOrder (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id INTEGER,
    order_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    total_amount REAL,
    FOREIGN KEY (supplier_id) REFERENCES Supplier (id)
);

DROP TABLE IF EXISTS OrderItem;
CREATE TABLE OrderItem (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_order_id INTEGER,
    inventory_item_id INTEGER,
    quantity_ordered REAL,
    unit_price REAL,
    is_received INTEGER DEFAULT 0, -- 0:未入荷, 1:入荷済み
    received_date DATETIME,        -- 入荷日
    FOREIGN KEY (purchase_order_id) REFERENCES PurchaseOrder (id),
    FOREIGN KEY (inventory_item_id) REFERENCES InventoryItem (id)
);

DROP TABLE IF EXISTS InventoryHistory;
CREATE TABLE InventoryHistory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inventory_item_id INTEGER,
    change_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    quantity_change REAL,
    change_reason TEXT,
    FOREIGN KEY (inventory_item_id) REFERENCES InventoryItem (id)
);
