import http.server
import socketserver
from socketserver import ThreadingMixIn
import sqlite3
from urllib.parse import urlparse, parse_qs
import json
from datetime import datetime
import csv
import io
import os
import shutil
import zipfile

PORT = 8501

# Constants
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'surgery.db')
SURGERY_USERNAME = "2466"  # Default credentials
SURGERY_PASSWORD = "2466"

# Base paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')

def init_db():
    """Initialize the surgery scheduling database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS SurgerySchedule (
            ID INTEGER PRIMARY KEY AUTOINCREMENT,
            Department TEXT NOT NULL,
            Date TEXT NOT NULL,
            BedNumber TEXT NOT NULL,
            PatientName TEXT NOT NULL,
            Gender TEXT NOT NULL,
            Age INTEGER NOT NULL,
            HospitalNumber TEXT NOT NULL,
            Diagnosis TEXT NOT NULL,
            Operation TEXT NOT NULL,
            MainSurgeon TEXT NOT NULL,
            Assistant TEXT NOT NULL,
            AnesthesiaDoctor TEXT NOT NULL,
            AnesthesiaType TEXT NOT NULL,
            PreOpPrep TEXT,
            OperationOrder INTEGER NOT NULL,
            Creator TEXT NOT NULL,
            Editor TEXT NOT NULL,
            CreatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UpdatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

class SurgeryHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        if path == '/':
            # Check if user is authenticated
            params = parse_qs(parsed_path.query)
            is_authenticated = params.get('auth', [''])[0] == 'true'
            
            if is_authenticated:
                self.send_file('templates/surgery_schedule.html')
            else:
                self.send_file('templates/surgery_login.html')
                
        elif path == '/api/surgeries':
            self.handle_get_surgeries()
        elif path == '/api/surgeries/export':
            self.handle_export_surgeries()
        elif path == '/api/surgeries/history':
            self.handle_get_history()
        elif path.startswith('/static/'):
            # Serve static files
            self.path = path
            return http.server.SimpleHTTPRequestHandler.do_GET(self)
        else:
            self.send_error(404)

    def do_POST(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        if path == '/api/surgery/login':
            self.handle_surgery_login()
        elif path == '/api/surgery/add':
            self.handle_add_surgery()
        elif path == '/api/surgery/edit':
            self.handle_edit_surgery()
        elif path == '/api/surgery/delete':
            self.handle_delete_surgery()
        elif path == '/api/database/backup':
            self.handle_backup_database()
        else:
            self.send_error(404)

    def handle_surgery_login(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length).decode('utf-8')
        data = json.loads(post_data)
        
        username = data.get('username')
        password = data.get('password')
        
        if username == SURGERY_USERNAME and password == SURGERY_PASSWORD:
            self.send_json({
                'success': True,
                'message': '登录成功'
            })
        else:
            self.send_json({
                'success': False,
                'message': '用户名或密码错误'
            })

    def handle_get_surgeries(self):
        params = parse_qs(urlparse(self.path).query)
        date = params.get('date', [datetime.now().strftime('%Y-%m-%d')])[0]
        department = params.get('department', ['二病区'])[0]
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT * FROM SurgerySchedule 
                WHERE Date = ? AND Department = ?
                ORDER BY OperationOrder
            ''', (date, department))
            
            columns = [description[0] for description in cursor.description]
            surgeries = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
            self.send_json({
                'success': True,
                'surgeries': surgeries
            })
        except Exception as e:
            self.send_json({
                'success': False,
                'message': str(e)
            })
        finally:
            conn.close()

    def handle_add_surgery(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length).decode('utf-8')
        data = json.loads(post_data)
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO SurgerySchedule (
                    Department, Date, BedNumber, PatientName, Gender, Age,
                    HospitalNumber, Diagnosis, Operation, MainSurgeon,
                    Assistant, AnesthesiaDoctor, AnesthesiaType, PreOpPrep,
                    OperationOrder, Creator, Editor
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data['Department'], data['Date'], data['BedNumber'],
                data['PatientName'], data['Gender'], data['Age'],
                data['HospitalNumber'], data['Diagnosis'], data['Operation'],
                data['MainSurgeon'], data['Assistant'], data['AnesthesiaDoctor'],
                data['AnesthesiaType'], data.get('PreOpPrep', ''),
                data['OperationOrder'], data['Creator'], data['Creator']
            ))
            
            conn.commit()
            self.send_json({
                'success': True,
                'message': '手术安排添加成功'
            })
        except Exception as e:
            self.send_json({
                'success': False,
                'message': str(e)
            })
        finally:
            conn.close()

    def handle_edit_surgery(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length).decode('utf-8')
        data = json.loads(post_data)
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE SurgerySchedule 
                SET Date=?, BedNumber=?, PatientName=?, Gender=?, Age=?,
                    HospitalNumber=?, Diagnosis=?, Operation=?, MainSurgeon=?,
                    Assistant=?, AnesthesiaDoctor=?, AnesthesiaType=?,
                    PreOpPrep=?, OperationOrder=?, Editor=?, UpdatedAt=CURRENT_TIMESTAMP
                WHERE ID=?
            ''', (
                data['Date'], data['BedNumber'], data['PatientName'],
                data['Gender'], data['Age'], data['HospitalNumber'],
                data['Diagnosis'], data['Operation'], data['MainSurgeon'],
                data['Assistant'], data['AnesthesiaDoctor'], data['AnesthesiaType'],
                data.get('PreOpPrep', ''), data['OperationOrder'],
                data.get('Editor', '系统用户'), data['ID']
            ))
            
            conn.commit()
            self.send_json({
                'success': True,
                'message': '手术安排已更新'
            })
        except Exception as e:
            self.send_json({
                'success': False,
                'message': str(e)
            })
        finally:
            conn.close()

    def handle_delete_surgery(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length).decode('utf-8')
        data = json.loads(post_data)
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute('DELETE FROM SurgerySchedule WHERE ID=?', (data['id'],))
            conn.commit()
            self.send_json({
                'success': True,
                'message': '手术安排已删除'
            })
        except Exception as e:
            self.send_json({
                'success': False,
                'message': str(e)
            })
        finally:
            conn.close()

    def handle_export_surgeries(self):
        params = parse_qs(urlparse(self.path).query)
        start_date = params.get('start_date', [''])[0]
        end_date = params.get('end_date', [''])[0]
        department = params.get('department', [''])[0]
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        try:
            if department == 'all':
                # Query for all departments
                query = '''
                    SELECT Date, Department, BedNumber, PatientName, Gender, Age,
                           HospitalNumber, Diagnosis, Operation, MainSurgeon,
                           Assistant, AnesthesiaDoctor, AnesthesiaType, PreOpPrep,
                           OperationOrder
                    FROM SurgerySchedule
                    WHERE Date BETWEEN ? AND ?
                    ORDER BY Date, Department, OperationOrder
                '''
                cursor.execute(query, (start_date, end_date))
            else:
                # Original single department query
                query = '''
                    SELECT Date, Department, BedNumber, PatientName, Gender, Age,
                           HospitalNumber, Diagnosis, Operation, MainSurgeon,
                           Assistant, AnesthesiaDoctor, AnesthesiaType, PreOpPrep,
                           OperationOrder
                    FROM SurgerySchedule
                    WHERE Department = ?
                    AND Date BETWEEN ? AND ?
                    ORDER BY Date, OperationOrder
                '''
                cursor.execute(query, (department, start_date, end_date))
            
            rows = cursor.fetchall()
            
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(['日期', '病区', '床号', '姓名', '性别', '年龄',
                           '住院号', '临床诊断', '术式', '主刀',
                           '助手', '管床医师', '麻醉', '术前准备', '台次'])
            writer.writerows(rows)
            
            self.send_response(200)
            self.send_header('Content-Type', 'text/csv')
            self.send_header('Content-Disposition', 
                           f'attachment; filename=surgeries_{start_date}_to_{end_date}.csv')
            self.end_headers()
            self.wfile.write(output.getvalue().encode('utf-8-sig'))
            
        finally:
            conn.close()

    def handle_get_history(self):
        params = parse_qs(urlparse(self.path).query)
        start_date = params.get('start_date', [''])[0]
        end_date = params.get('end_date', [''])[0]
        department = params.get('department', [''])[0]
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT * FROM SurgerySchedule 
                WHERE Department = ? 
                AND Date BETWEEN ? AND ?
                ORDER BY Date, OperationOrder
            ''', (department, start_date, end_date))
            
            columns = [description[0] for description in cursor.description]
            surgeries = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
            # Group surgeries by date
            history_data = {}
            for surgery in surgeries:
                date = surgery['Date']
                if date not in history_data:
                    history_data[date] = []
                history_data[date].append(surgery)
            
            self.send_json({
                'success': True,
                'history': history_data
            })
        except Exception as e:
            self.send_json({
                'success': False,
                'message': str(e)
            })
        finally:
            conn.close()

    def handle_backup_database(self):
        try:
            backup_dir = os.path.join(os.path.dirname(DB_PATH), 'backups')
            os.makedirs(backup_dir, exist_ok=True)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_file = os.path.join(backup_dir, f'surgery_backup_{timestamp}.db')
            
            shutil.copy2(DB_PATH, backup_file)
            
            zip_file = backup_file + '.zip'
            with zipfile.ZipFile(zip_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
                zipf.write(backup_file, os.path.basename(backup_file))
            
            os.remove(backup_file)
            
            self.send_json({
                'success': True,
                'message': '数据库备份成功',
                'backup_file': os.path.basename(zip_file)
            })
        except Exception as e:
            self.send_json({
                'success': False,
                'message': f'备份失败: {str(e)}'
            })

    def send_file(self, filename):
        try:
            # Convert relative path to absolute path
            if filename.startswith('templates/'):
                filepath = os.path.join(BASE_DIR, filename)
            else:
                filepath = filename
                
            with open(filepath, 'rb') as f:
                content = f.read().decode('utf-8')
                self.send_response(200)
                if filename.endswith('.html'):
                    self.send_header('Content-type', 'text/html; charset=utf-8')
                elif filename.endswith('.js'):
                    self.send_header('Content-type', 'application/javascript')
                elif filename.endswith('.css'):
                    self.send_header('Content-type', 'text/css')
                self.end_headers()
                self.wfile.write(content.encode('utf-8'))
        except FileNotFoundError:
            print(f"File not found: {filename}")
            self.send_error(404)
        except Exception as e:
            print(f"Error sending file {filename}: {str(e)}")
            self.send_error(500)

    def send_json(self, data):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

class ThreadedHTTPServer(ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True

def run_server():
    init_db()
    try:
        with ThreadedHTTPServer(("", PORT), SurgeryHandler) as httpd:
            print(f"Server started at http://localhost:{PORT}")
            print("Press Ctrl+C to stop the server")
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        httpd.server_close()

if __name__ == '__main__':
    run_server() 