import os
import sqlite3
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, g

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'warehouse-secret-key-2024')

DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'warehouse.db')


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DATABASE)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number INTEGER NOT NULL,
            article TEXT NOT NULL,
            name TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 0,
            comment TEXT DEFAULT ''
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            old_quantity INTEGER NOT NULL,
            new_quantity INTEGER NOT NULL,
            change_date TEXT NOT NULL,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        )
    ''')
    db.commit()
    db.close()


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        password = request.form.get('password', '')
        if password == '0880':
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            error = 'invalid'
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))


@app.route('/')
@login_required
def index():
    return render_template('index.html')


@app.route('/api/products', methods=['GET'])
@login_required
def get_products():
    db = get_db()
    search = request.args.get('search', '').strip()
    if search:
        products = db.execute(
            'SELECT * FROM products WHERE article LIKE ? OR name LIKE ? ORDER BY number ASC',
            (f'%{search}%', f'%{search}%')
        ).fetchall()
    else:
        products = db.execute('SELECT * FROM products ORDER BY number ASC').fetchall()
    return jsonify([dict(row) for row in products])


@app.route('/api/products', methods=['POST'])
@login_required
def add_product():
    db = get_db()
    data = request.get_json()
    article = data.get('article', '').strip()
    name = data.get('name', '').strip()
    quantity = int(data.get('quantity', 0))
    comment = data.get('comment', '').strip()

    if not article or not name:
        return jsonify({'error': 'Article and name are required'}), 400

    # Get next order number
    row = db.execute('SELECT COALESCE(MAX(number), 0) + 1 AS next_num FROM products').fetchone()
    next_number = row['next_num']

    db.execute(
        'INSERT INTO products (number, article, name, quantity, comment) VALUES (?, ?, ?, ?, ?)',
        (next_number, article, name, quantity, comment)
    )
    db.commit()

    # Record initial quantity in history if quantity > 0
    if quantity != 0:
        product = db.execute('SELECT id FROM products WHERE number = ?', (next_number,)).fetchone()
        db.execute(
            'INSERT INTO history (product_id, old_quantity, new_quantity, change_date) VALUES (?, ?, ?, ?)',
            (product['id'], 0, quantity, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        db.commit()

    return jsonify({'success': True}), 201


@app.route('/api/products/<int:product_id>', methods=['PUT'])
@login_required
def update_product(product_id):
    db = get_db()
    data = request.get_json()
    article = data.get('article', '').strip()
    name = data.get('name', '').strip()
    new_quantity = int(data.get('quantity', 0))
    comment = data.get('comment', '').strip()

    if not article or not name:
        return jsonify({'error': 'Article and name are required'}), 400

    # Get current product
    product = db.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()
    if not product:
        return jsonify({'error': 'Product not found'}), 404

    old_quantity = product['quantity']

    db.execute(
        'UPDATE products SET article = ?, name = ?, quantity = ?, comment = ? WHERE id = ?',
        (article, name, new_quantity, comment, product_id)
    )

    # Record history if quantity changed
    if old_quantity != new_quantity:
        db.execute(
            'INSERT INTO history (product_id, old_quantity, new_quantity, change_date) VALUES (?, ?, ?, ?)',
            (product_id, old_quantity, new_quantity, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )

    db.commit()
    return jsonify({'success': True})


@app.route('/api/products/<int:product_id>', methods=['DELETE'])
@login_required
def delete_product(product_id):
    db = get_db()
    product = db.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()
    if not product:
        return jsonify({'error': 'Product not found'}), 404

    db.execute('DELETE FROM history WHERE product_id = ?', (product_id,))
    db.execute('DELETE FROM products WHERE id = ?', (product_id,))
    db.commit()
    return jsonify({'success': True})


@app.route('/api/products/<int:product_id>/history', methods=['GET'])
@login_required
def get_history(product_id):
    db = get_db()
    history = db.execute(
        'SELECT * FROM history WHERE product_id = ? ORDER BY change_date DESC',
        (product_id,)
    ).fetchall()
    return jsonify([dict(row) for row in history])


init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)