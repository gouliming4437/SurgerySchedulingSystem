import http.server
import socketserver
import cgi
import re
from html.parser import HTMLParser
import os
from urllib.parse import parse_qs

class SurgeryInfoParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.data = {
            'bed_number': '',
            'patient_name': '',
            'gender': '',
            'age': '',
            'patient_number': '',
            'diagnosis': '',
            'operation': '',
            'surgeon': '',
            'anesthesia': ''
        }
        self.current_tag = ''
        self.found_bed = False
        self.found_name = False
        self.found_number = False
        self.found_operation = False
        self.found_surgeon = False
        self.found_anesthesia = False
        self.expect_data = None
        
    def handle_starttag(self, tag, attrs):
        self.current_tag = tag
        if tag == 'customtag:ded_y' or tag == 'customtag:de_y':
            for attr in attrs:
                if attr[0] == 'id':
                    if attr[1] == 'STD_DE_SEX':
                        self.expect_data = 'gender'
                    elif attr[1] == 'STD_DE_AGE':
                        self.expect_data = 'age'
                    elif attr[1] == 'STD_DE_DIAGNOSIS_NAME|3|2':
                        self.expect_data = 'diagnosis'
        elif tag == 'img':
            for attr in attrs:
                if attr[0] == 'imgcontent':
                    if self.found_surgeon:
                        self.data['surgeon'] = attr[1]
                        self.found_surgeon = False
        else:
            for attr in attrs:
                # For bed number
                if attr[0] == 'align' and attr[1] == 'right':
                    self.found_bed = True
                # For patient name
                elif attr[0] == 'value' and attr[1] == 'patient.name':
                    self.found_name = True
                # For patient number
                elif attr[0] == 'value' and attr[1] == 'residence.event':
                    self.found_number = True
                # For operation
                elif attr[0] == 'id' and attr[1] == 'EXT_DE_939FC1AD_31BD_43D0_9385_F5D0F2B0CA4F':
                    self.found_operation = True
                # For anesthesia
                elif attr[0] == 'id' and attr[1] == 'EXT_DE_046B7DD6_2FF3_41C6_86D5_9F5C151DE1DB':
                    self.found_anesthesia = True

    def handle_data(self, data):
        data = data.strip()
        if not data:
            return
            
        # Set flag for surgeon
        if data == "经治医生:":
            self.found_surgeon = True
            
        # Handle bed number
        if self.found_bed:
            if data == "床号:":
                self.found_bed = 'next'
            elif self.found_bed == 'next':
                self.data['bed_number'] = data
                self.found_bed = False
                
        # Handle patient name
        if self.found_name:
            self.data['patient_name'] = data
            self.found_name = False
            
        # Handle patient number
        if self.found_number:
            self.data['patient_number'] = data
            self.found_number = False
            
        # Handle operation
        if self.found_operation:
            self.data['operation'] = data.strip()
            self.found_operation = False
            
        # Handle anesthesia
        if self.found_anesthesia:
            self.data['anesthesia'] = data.strip()
            self.found_anesthesia = False
            
        # Handle gender, age, and diagnosis
        if self.expect_data:
            if self.expect_data == 'gender':
                self.data['gender'] = data
            elif self.expect_data == 'age':
                self.data['age'] = data.replace('岁', '')
            elif self.expect_data == 'diagnosis':
                self.data['diagnosis'] = data
            self.expect_data = None

class RequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            
            with open('upload.html', 'rb') as f:
                self.wfile.write(f.read())
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == '/upload':
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={'REQUEST_METHOD': 'POST',
                        'CONTENT_TYPE': self.headers['Content-Type']}
            )

            file_item = form['file']
            if file_item.filename:
                content = file_item.file.read().decode('gb2312', errors='ignore')
                
                parser = SurgeryInfoParser()
                parser.feed(content)
                
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                
                response = f"""
                <html>
                <head>
                    <title>手术信息提取结果</title>
                    <meta charset="utf-8">
                    <style>
                        table {{ border-collapse: collapse; width: 80%; margin: 20px auto; }}
                        th, td {{ border: 1px solid black; padding: 8px; text-align: left; }}
                        th {{ background-color: #f2f2f2; }}
                    </style>
                </head>
                <body>
                    <h2 style="text-align: center">提取结果</h2>
                    <table>
                        <tr><th>字段</th><th>值</th></tr>
                        <tr><td>床号</td><td>{parser.data['bed_number']}</td></tr>
                        <tr><td>姓名</td><td>{parser.data['patient_name']}</td></tr>
                        <tr><td>性别</td><td>{parser.data['gender']}</td></tr>
                        <tr><td>年龄</td><td>{parser.data['age']}</td></tr>
                        <tr><td>住院号</td><td>{parser.data['patient_number']}</td></tr>
                        <tr><td>诊断</td><td>{parser.data['diagnosis']}</td></tr>
                        <tr><td>手术名称</td><td>{parser.data['operation']}</td></tr>
                        <tr><td>经治医生</td><td>{parser.data['surgeon']}</td></tr>
                        <tr><td>麻醉名称</td><td>{parser.data['anesthesia']}</td></tr>
                    </table>
                    <div style="text-align: center">
                        <a href="/" style="text-decoration: none">
                            <button style="padding: 10px 20px">返回上传页面</button>
                        </a>
                    </div>
                </body>
                </html>
                """
                self.wfile.write(response.encode('utf-8'))

def run_server(port=8000):
    with socketserver.TCPServer(("", port), RequestHandler) as httpd:
        print(f"Server running at http://localhost:{port}")
        httpd.serve_forever()

if __name__ == '__main__':
    run_server() 