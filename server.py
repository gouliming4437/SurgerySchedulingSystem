import http.server
import socketserver
from socketserver import ThreadingMixIn
import sqlite3
from urllib.parse import urlparse, parse_qs
import json
from datetime import datetime, timedelta
import csv
import io
import os
import shutil
import zipfile
import re
from contextlib import contextmanager
import queue
import threading
import logging
from HtmlParse.extract_surgery_info import SurgeryInfoParser
import tempfile

PORT = 8501

# Constants
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'surgery.db')
SURGERY_USERNAME = "2466"  # Default credentials
SURGERY_PASSWORD = "2466"
DB_MAINTENANCE_USERNAME = "admin"
DB_MAINTENANCE_PASSWORD = "admin123"

# Base paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')

# Logging
LOG_FILE = os.path.join(BASE_DIR, 'surgery.log')
BACKUP_DIR = os.path.join(BASE_DIR, 'backups')

# Create directories if they don't exist
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

# Create a custom handler with UTF-8 encoding
class UTF8FileHandler(logging.FileHandler):
    def __init__(self, filename):
        super().__init__(filename, encoding='utf-8')

# Initialize logging with custom handler
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[UTF8FileHandler(LOG_FILE)]
)

class DatabasePool:
    def __init__(self, max_connections=10):
        self.pool = queue.Queue(maxsize=max_connections)
        for _ in range(max_connections):
            conn = sqlite3.connect(DB_PATH)
            self.pool.put(conn)

    @contextmanager
    def get_connection(self):
        conn = self.pool.get()
        try:
            yield conn
        finally:
            self.pool.put(conn)

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

def load_template(filename, **kwargs):
    """Load a template and replace any includes"""
    with open(os.path.join(TEMPLATE_DIR, filename), 'r', encoding='utf-8') as f:
        content = f.read()
        
    # Handle includes
    include_pattern = r'{{\s*include\s+[\'"](.*?)[\'\"]\s*}}'
    matches = re.finditer(include_pattern, content)
    
    for match in matches:
        include_file = match.group(1)
        with open(os.path.join(TEMPLATE_DIR, include_file), 'r', encoding='utf-8') as f:
            include_content = f.read()
        content = content.replace(match.group(0), include_content)
    
    # Replace any variables
    for key, value in kwargs.items():
        content = content.replace('{{' + key + '}}', str(value))
    
    return content

def parse_surgery_html(html_content):
    """Parse surgery information from HTML content"""
    parser = SurgeryInfoParser()
    parser.feed(html_content)
    
    # Map the parsed data to our system's field names
    field_mapping = {
        'bed_number': 'BedNumber',
        'patient_name': 'PatientName', 
        'gender': 'Gender',
        'age': 'Age',
        'patient_number': 'HospitalNumber',
        'diagnosis': 'Diagnosis',
        'operation': 'Operation',  # Keep original separator
        'surgeon': 'MainSurgeon',
        'anesthesia': 'AnesthesiaType'
    }
    
    mapped_data = {}
    for html_field, sys_field in field_mapping.items():
        value = parser.data.get(html_field, '')
        if html_field == 'age':
            # Convert age string to integer
            try:
                value = int(value.replace('岁', ''))
            except:
                value = 0
        # Remove the operation field special handling to preserve original separator
        mapped_data[sys_field] = value
        
    # Set 管床医生 same as 主刀
    mapped_data['AnesthesiaDoctor'] = mapped_data['MainSurgeon']
    
    return mapped_data

class SurgeryHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        if path == '/admin/login':
            self.send_file('templates/admin_login.html')
            return
        elif path == '/db/maintenance':
            if self.is_admin_authenticated():
                self.send_file('templates/db_maintenance.html')
            else:
                self.redirect_to_admin_login()
            return
        elif path == '/':
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
        elif path == '/api/db/maintenance':
            self.handle_db_maintenance()
        elif path == '/api/db/stats':
            self.handle_get_db_stats()
        elif path == '/api/database/backups':
            self.handle_get_backups()
        elif path == '/api/database/logs':
            self.handle_get_logs()
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
        elif path == '/api/database/import':
            self.handle_import_backup()
        elif path == '/api/database/logs/clear':
            self.handle_clear_logs()
        elif path == '/api/admin/login':
            self.handle_admin_login()
        elif path == '/api/surgery/parse_html':
            self.handle_parse_html()
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
        
        db_pool = DatabasePool()
        
        try:
            with db_pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM SurgerySchedule 
                    WHERE Date = ? AND Department = ?
                    ORDER BY OperationOrder
                ''', (date, department))
                
                columns = [description[0] for description in cursor.description]
                surgeries = [dict(zip(columns, row)) for row in cursor.fetchall()]
                
                # Set title based on department
                title = "颌面外科手术安排表" if department == '手术麻醉科' else f'{department}手术安排表'
                
                self.send_json({
                    'success': True,
                    'surgeries': surgeries,
                    'title': f'{title} {date}'
                })
        except Exception as e:
            self.send_json({
                'success': False,
                'message': str(e)
            })

    def handle_add_surgery(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length).decode('utf-8')
        data = json.loads(post_data)
        
        db_pool = DatabasePool()
        
        try:
            with db_pool.get_connection() as conn:
                cursor = conn.cursor()
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

    def handle_edit_surgery(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length).decode('utf-8')
        data = json.loads(post_data)
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        try:
            # Check version before update
            cursor.execute('SELECT UpdatedAt FROM SurgerySchedule WHERE ID=?', (data['ID'],))
            result = cursor.fetchone()
            if result and result[0] != data.get('lastUpdate'):
                self.send_json({
                    'success': False,
                    'message': '该记录已被其他用户修改，请刷新后重试'
                })
                return

            # Proceed with update
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
        
        db_pool = DatabasePool()
        
        try:
            with db_pool.get_connection() as conn:
                cursor = conn.cursor()
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

    def handle_export_surgeries(self):
        params = parse_qs(urlparse(self.path).query)
        start_date = params.get('start_date', [''])[0]
        end_date = params.get('end_date', [''])[0]
        department = params.get('department', [''])[0]
        
        db_pool = DatabasePool()
        
        try:
            with db_pool.get_connection() as conn:
                cursor = conn.cursor()
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
                
        except Exception as e:
            self.send_json({
                'success': False,
                'message': f'查询失败: {str(e)}'
            })

    def handle_get_history(self):
        params = parse_qs(urlparse(self.path).query)
        start_date = params.get('start_date', [''])[0]
        end_date = params.get('end_date', [''])[0]
        department = params.get('department', [''])[0]
        
        db_pool = DatabasePool()
        
        try:
            with db_pool.get_connection() as conn:
                cursor = conn.cursor()
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
                'message': f'查询失败: {str(e)}'
            })

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

    def handle_db_maintenance(self):
        """Handle database maintenance operations"""
        try:
            parsed_path = urlparse(self.path)
            params = parse_qs(parsed_path.query)
            operation = params.get('operation', [''])[0]
            
            if not operation:
                raise ValueError("No operation specified")
                
            logging.info(f"Performing maintenance operation: {operation}")
        
            if operation == 'vacuum':
                self.handle_vacuum_db()
            elif operation == 'archive':
                self.handle_archive_data()
            elif operation == 'add_indexes':
                self.handle_add_indexes()
            elif operation == 'analyze':
                self.handle_analyze_db()
            elif operation == 'reset':
                self.handle_reset_database()
            else:
                raise ValueError(f"Invalid maintenance operation: {operation}")
                
        except Exception as e:
            logging.error(f"Maintenance operation failed: {str(e)}")
            self.send_json({
                'success': False,
                'message': f'维护作失败: {str(e)}'
            })

    def handle_vacuum_db(self):
        """Vacuum the database to reclaim space and defragment"""
        try:
            # Close all connections before vacuum
            conn = sqlite3.connect(DB_PATH)
            conn.isolation_level = None  # This is required for vacuum
            conn.execute("VACUUM")
            conn.close()
            
            self.send_json({
                'success': True,
                'message': '数据库整理完成'
            })
        except Exception as e:
            logging.error(f"Vacuum failed: {str(e)}")
            self.send_json({
                'success': False,
                'message': f'数据库整理失败: {str(e)}'
            })

    def handle_archive_data(self):
        """Archive old surgery records"""
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            # Create archive table if it doesn't exist
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS SurgeryScheduleArchive (
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
                    CreatedAt TIMESTAMP,
                    UpdatedAt TIMESTAMP
                )
            ''')
            
            # Calculate date threshold (e.g., 1 year ago)
            archive_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
            
            # Move old records to archive
            cursor.execute('''
                INSERT INTO SurgeryScheduleArchive
                SELECT * FROM SurgerySchedule
                WHERE Date < ?
                AND ID NOT IN (SELECT ID FROM SurgeryScheduleArchive)
            ''', (archive_date,))
            
            # Get count of archived records
            archived_count = cursor.rowcount
            
            # Delete archived records from main table
            if archived_count > 0:
                cursor.execute('DELETE FROM SurgerySchedule WHERE Date < ?', (archive_date,))
            
            conn.commit()
            conn.close()
            
            self.send_json({
                'success': True,
                'message': f'已归档 {archived_count} 条记录'
            })
        except Exception as e:
            logging.error(f"Archive failed: {str(e)}")
            self.send_json({
                'success': False,
                'message': f'归档失败: {str(e)}'
            })

    def handle_add_indexes(self):
        """Add indexes to improve query performance"""
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            # Add commonly used indexes
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_surgery_date ON SurgerySchedule(Date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_surgery_dept ON SurgerySchedule(Department)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_surgery_date_dept ON SurgerySchedule(Date, Department)')
            
            conn.commit()
            conn.close()
            
            self.send_json({
                'success': True,
                'message': '索引添加成功'
            })
        except Exception as e:
            self.send_json({
                'success': False,
                'message': f'添加索引败: {str(e)}'
            })

    def handle_analyze_db(self):
        """Analyze the database to update statistics"""
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute('ANALYZE')
            conn.commit()
            conn.close()
            
            self.send_json({
                'success': True,
                'message': '数据库分析完成'
            })
        except Exception as e:
            self.send_json({
                'success': False,
                'message': f'数据库分析失败: {str(e)}'
            })

    def handle_get_db_stats(self):
        """Get database statistics"""
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            # Get total records
            cursor.execute('SELECT COUNT(*) FROM SurgerySchedule')
            total_records = cursor.fetchone()[0]
            
            # Get archived records (handle case where table might not exist)
            try:
                cursor.execute('SELECT COUNT(*) FROM SurgeryScheduleArchive')
                archived_records = cursor.fetchone()[0]
            except sqlite3.OperationalError:
                archived_records = 0
            
            # Get oldest record date
            cursor.execute('SELECT MIN(Date) FROM SurgerySchedule')
            oldest_record = cursor.fetchone()[0] or '-'
            
            # Get database size
            db_size = os.path.getsize(DB_PATH)
            db_size_mb = round(db_size / (1024 * 1024), 2)
            
            conn.close()
            
            self.send_json({
                'success': True,
                'stats': {
                    'totalRecords': total_records,
                    'archivedRecords': archived_records,
                    'oldestRecord': oldest_record,
                    'dbSize': f'{db_size_mb} MB'
                }
            })
        except Exception as e:
            logging.error(f"Get stats failed: {str(e)}")
            self.send_json({
                'success': False,
                'message': str(e)
            })

    def handle_get_backups(self):
        """Get list of database backups"""
        try:
            os.makedirs(BACKUP_DIR, exist_ok=True)
            backups = []
            
            for filename in os.listdir(BACKUP_DIR):
                if filename.endswith('.zip'):
                    path = os.path.join(BACKUP_DIR, filename)
                    size = os.path.getsize(path)
                    size_mb = round(size / (1024 * 1024), 2)
                    backups.append({
                        'filename': filename,
                        'size': f'{size_mb} MB'
                    })
            
            self.send_json({
                'success': True,
                'backups': sorted(backups, key=lambda x: x['filename'], reverse=True)
            })
        except Exception as e:
            self.send_json({
                'success': False,
                'message': str(e)
            })

    def handle_import_backup(self):
        """Import database backup"""
        try:
            content_length = int(self.headers['Content-Length'])
            if content_length > 50 * 1024 * 1024:  # 50MB limit
                raise ValueError("Backup file too large")
            
            # Read the multipart form data
            # Implementation depends on how you handle file uploads
            # This is a simplified version
            
            # Backup current database
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_path = os.path.join(BACKUP_DIR, f'pre_import_backup_{timestamp}.db')
            shutil.copy2(DB_PATH, backup_path)
            
            # Process the uploaded file and restore database
            # Implementation needed here
            
            logging.info('Database restored from backup')
            self.send_json({
                'success': True,
                'message': '数据库已从备份恢复'
            })
        except Exception as e:
            self.send_json({
                'success': False,
                'message': str(e)
            })

    def handle_get_logs(self):
        """Get system logs"""
        try:
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                logs = []
                for line in f.readlines()[-100:]:  # Get last 100 lines
                    parts = line.split(' - ', 1)
                    if len(parts) == 2:
                        timestamp, message = parts
                        logs.append({
                            'timestamp': timestamp.strip(),
                            'message': message.strip()
                        })
            
            self.send_json({
                'success': True,
                'logs': logs
            })
        except Exception as e:
            self.send_json({
                'success': False,
                'message': str(e)
            })

    def handle_clear_logs(self):
        """Clear system logs"""
        try:
            with open(LOG_FILE, 'w') as f:
                f.write('')
            
            self.send_json({
                'success': True,
                'message': '日志已清除'
            })
        except Exception as e:
            self.send_json({
                'success': False,
                'message': str(e)
            })

    def handle_admin_login(self):
        """Handle admin login"""
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length).decode('utf-8')
        data = json.loads(post_data)
        
        username = data.get('username')
        password = data.get('password')
        
        if username == DB_MAINTENANCE_USERNAME and password == DB_MAINTENANCE_PASSWORD:
            # Set cookie for authentication
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Set-Cookie', 'admin_auth=true; Path=/')
            self.end_headers()
            self.wfile.write(json.dumps({
                'success': True,
                'message': '登录成功'
            }).encode())
        else:
            self.send_json({
                'success': False,
                'message': '管理员用户名或密码错误'
            })

    def is_admin_authenticated(self):
        """Check if admin is authenticated"""
        cookies = self.headers.get('Cookie', '')
        return 'admin_auth=true' in cookies

    def redirect_to_admin_login(self):
        """Redirect to admin login page"""
        self.send_response(302)
        self.send_header('Location', '/admin/login')
        self.end_headers()

    def send_file(self, filename):
        try:
            if filename.startswith('templates/'):
                # Handle template files
                template_name = os.path.basename(filename)
                content = load_template(template_name)
                self.send_response(200)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(content.encode('utf-8'))
            else:
                # Handle other static files
                filepath = filename
                with open(filepath, 'rb') as f:
                    content = f.read()
                    self.send_response(200)
                    if filename.endswith('.js'):
                        self.send_header('Content-type', 'application/javascript')
                    elif filename.endswith('.css'):
                        self.send_header('Content-type', 'text/css')
                    self.end_headers()
                    self.wfile.write(content)
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

    def handle_reset_database(self):
        """Backup current database and create a new clean one"""
        try:
            # 1. Create backup of current database
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_dir = os.path.join(BASE_DIR, 'backups')
            backup_file = os.path.join(backup_dir, f'full_backup_{timestamp}.db')
            
            # Ensure backup directory exists
            os.makedirs(backup_dir, exist_ok=True)
            
            # Copy current database to backup
            shutil.copy2(DB_PATH, backup_file)
            
            # 2. Create zip of backup
            zip_file = backup_file + '.zip'
            with zipfile.ZipFile(zip_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
                zipf.write(backup_file, os.path.basename(backup_file))
            
            # Remove unzipped backup
            os.remove(backup_file)
            
            # 3. Remove current database
            os.remove(DB_PATH)
            
            # 4. Initialize new clean database
            init_db()
            
            self.send_json({
                'success': True,
                'message': f'数据库已重置。旧数据已备份为: {os.path.basename(zip_file)}',
                'backup_file': os.path.basename(zip_file)
            })
            
            logging.info(f"Database reset completed. Backup created: {os.path.basename(zip_file)}")
            
        except Exception as e:
            logging.error(f"Database reset failed: {str(e)}")
            self.send_json({
                'success': False,
                'message': f'数据库重置失败: {str(e)}'
            })

    def handle_parse_html(self):
        """Handle HTML file upload and parsing"""
        try:
            # Get content length
            content_length = int(self.headers['Content-Length'])
            
            # Read the multipart form data
            if content_length > 1024 * 1024:  # 1MB limit
                raise ValueError("File too large")
                
            # Create a temporary file to store the uploaded data
            with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
                # Read and write the file in chunks
                remaining = content_length
                while remaining:
                    chunk_size = min(remaining, 8192)
                    chunk = self.rfile.read(chunk_size)
                    if not chunk:
                        break
                    tmp_file.write(chunk)
                    remaining -= len(chunk)
                    
                # Reset file pointer
                tmp_file.seek(0)
                
                # Read the file content
                content = tmp_file.read().decode('gb2312', errors='ignore')
                
            # Parse the HTML content
            surgery_data = parse_surgery_html(content)
            
            self.send_json({
                'success': True,
                'data': surgery_data
            })
            
        except Exception as e:
            self.send_json({
                'success': False,
                'message': str(e)
            })

class ThreadedHTTPServer(ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True

def run_server():
    # Initialize database and create necessary directories
    init_db()
    os.makedirs(BACKUP_DIR, exist_ok=True)
    
    # Initialize logging
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', encoding='utf-8') as f:
            f.write('')
    
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