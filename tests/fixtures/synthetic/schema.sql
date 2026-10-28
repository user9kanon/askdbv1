-- Synthetic retail database for data-agnosticism tests (SPEC 11.4).
-- Different tables and scoping column from CloudMetrics, no metrics, and a
-- multi-hop chain: order_items -> orders -> accounts.
CREATE TABLE accounts (
  account_id    INTEGER PRIMARY KEY,
  account_name  TEXT NOT NULL,
  territory     TEXT NOT NULL,
  contact_email TEXT,
  internal_note TEXT            -- not listed in the config: never copied
);
CREATE TABLE products (
  product_id INTEGER PRIMARY KEY,
  sku        TEXT NOT NULL,
  unit_price REAL NOT NULL
);
CREATE TABLE orders (
  order_id   INTEGER PRIMARY KEY,
  account_id INTEGER REFERENCES accounts(account_id),
  ordered_at DATETIME NOT NULL
);
CREATE TABLE order_items (
  item_id    INTEGER PRIMARY KEY,
  order_id   INTEGER REFERENCES orders(order_id),
  product_id INTEGER REFERENCES products(product_id),
  quantity   INTEGER NOT NULL
);

INSERT INTO accounts VALUES
  (1, 'Northwind', 'North', 'a@north.example', 'x'),
  (2, 'Southbay',  'South', 'b@south.example', 'y'),
  (3, 'Westend',   'West',  NULL,              'z'),
  (4, 'Islander',  'Isles', 'd@isles.example', NULL);  -- Isles is in no group
INSERT INTO products VALUES (1, 'SKU-A', 9.5), (2, 'SKU-B', 20.0);
INSERT INTO orders VALUES
  (10, 1, '2024-01-05 10:00:00'),
  (11, 2, '2024-02-10 11:30:00'),
  (12, 3, '2024-03-15 09:15:00'),
  (13, NULL, '2024-03-20 12:00:00'),               -- orphan: dropped from every scope
  (14, 4, '2024-04-01 08:00:00');
INSERT INTO order_items VALUES
  (100, 10, 1, 2), (101, 10, 2, 1), (102, 11, 1, 5),
  (103, 12, 2, 3), (104, 13, 1, 1), (105, 14, 2, 4);
