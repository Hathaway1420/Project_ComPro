
import os
import struct
from datetime import datetime
from collections import Counter

# --------------------------
# ค่าคงที่: ชื่อไฟล์ต่าง ๆ
# --------------------------
CUS_FILE = 'cus_notebook.dat'
NB_FILE = 'Info_notebook.dat'
SO_FILE = 'sold_out.dat'
REPORT_FILE = 'report.txt'

# --------------------------
# ฟังก์ชันช่วยเรื่องสตริงคงที่ (fixed-length)
# --------------------------
def to_fixed_bytes(text: str, size: int) -> bytes:
    """แปลงสตริงเป็น bytes แบบความยาวคงที่ (UTF-8), ตัดเกิน/เติมด้วย \x00"""
    raw = text.encode('utf-8', errors='ignore')
    if len(raw) > size:
        return raw[:size]
    return raw + b'\x00' * (size - len(raw))

def from_fixed_bytes(b: bytes) -> str:
    """แปลง bytes (ที่มี \x00 padding) กลับเป็นสตริง (UTF-8)"""
    return b.split(b'\x00', 1)[0].decode('utf-8', errors='ignore')

def input_int(prompt: str, allow_zero=True, positive_only=False):
    while True:
        s = input(prompt).strip()
        if not s:
            print("** กรุณากรอกตัวเลข **")
            continue
        if not s.lstrip('-').isdigit():
            print("** ต้องเป็นจำนวนเต็ม **")
            continue
        val = int(s)
        if not allow_zero and val == 0:
            print("** ต้องไม่เป็น 0 **")
            continue
        if positive_only and val < 0:
            print("** ต้องเป็นจำนวนเต็มบวก **")
            continue
        return val

def input_float(prompt: str, positive_only=False):
    while True:
        s = input(prompt).strip()
        try:
            val = float(s)
            if positive_only and val < 0:
                print("** ต้องเป็นจำนวนจริงบวก **")
                continue
            return val
        except ValueError:
            print("** ต้องเป็นจำนวนจริง **")

def input_fixed_str(prompt: str, size: int):
    s = input(prompt).strip()
    # ไม่จำกัดอักขระ แต่จะถูกตัดตามขนาดไบต์จริงเมื่อ pack
    return s

def input_status(prompt: str):
    while True:
        v = input_int(prompt + " (0/1): ", allow_zero=True, positive_only=False)
        if v in (0, 1):
            return v
        print("** ค่า status ต้องเป็น 0 หรือ 1 **")

# --------------------------
# โครงสร้างระเบียน + struct format
# เพิ่มฟิลด์ is_deleted:I ทุกไฟล์
# --------------------------

# 1) ลูกค้า
CUS_FMT = '<I I 12s 24s 12s 16s 12s'  # is_deleted, customer_id, name, address, brand, model, tel
CUS_SIZE = struct.calcsize(CUS_FMT)

# 2) โน้ตบุ๊ก
NB_FMT = '<I I 12s 16s I f I'          # is_deleted, notebook_id, brand, serial, rel, price, status(1=stock,0=sold)
NB_SIZE = struct.calcsize(NB_FMT)

# 3) ขายออก
SO_FMT = '<I I I I 12s 12s I'          # is_deleted, sold_out_id, notebook_id, customer_id, name, sold_date, status
SO_SIZE = struct.calcsize(SO_FMT)

# --------------------------
# ชั้นจัดการไฟล์ไบนารีทั่วไป
# --------------------------
class FixedRecordFile:
    def __init__(self, path: str, fmt: str, size: int, key_field: str):
        self.path = path
        self.fmt = fmt
        self.size = size
        self.key_field = key_field  # ชื่อฟิลด์ id ที่ใช้เป็น key
        self.index = {}             # map: id -> offset
        self.free_offsets = []      # รายการตำแหน่งที่ is_deleted=1
        self._ensure_file()
        self._scan()

    def _ensure_file(self):
        if not os.path.exists(self.path):
            with open(self.path, 'wb') as f:
                pass

    def _scan(self):
        """อ่านทั้งไฟล์ สร้างดัชนีและรายการช่องว่าง"""
        self.index.clear()
        self.free_offsets.clear()
        with open(self.path, 'rb') as f:
            offset = 0
            while True:
                chunk = f.read(self.size)
                if not chunk or len(chunk) < self.size:
                    break
                rec = struct.unpack(self.fmt, chunk)
                is_deleted = rec[0]
                # key อยู่ตำแหน่ง 1 เสมอ (หลัง is_deleted)
                key = rec[1]
                if is_deleted == 1:
                    self.free_offsets.append(offset)
                else:
                    self.index[key] = offset
                offset += self.size

    def _write_at(self, offset: int, packed: bytes):
        with open(self.path, 'r+b') as f:
            f.seek(offset)
            f.write(packed)

    def _append(self, packed: bytes) -> int:
        with open(self.path, 'ab') as f:
            pos = f.tell()
            f.write(packed)
            return pos

    def add(self, packed_with_id: bytes, record_id: int):
        """เพิ่มระเบียนใหม่: ถ้ามีช่องว่าง (deleted) จะเขียนทับก่อน มิฉะนั้น append"""
        if record_id in self.index:
            raise ValueError(f"ID {record_id} มีอยู่แล้ว")
        if self.free_offsets:
            offset = self.free_offsets.pop(0)
            self._write_at(offset, packed_with_id)
            self.index[record_id] = offset
        else:
            offset = self._append(packed_with_id)
            self.index[record_id] = offset
        return offset

    def get(self, record_id: int):
        if record_id not in self.index:
            return None, None
        offset = self.index[record_id]
        with open(self.path, 'rb') as f:
            f.seek(offset)
            data = f.read(self.size)
        return offset, struct.unpack(self.fmt, data)

    def update(self, record_id: int, packed: bytes):
        if record_id not in self.index:
            raise ValueError(f"ไม่พบ ID {record_id}")
        offset = self.index[record_id]
        self._write_at(offset, packed)

    def delete(self, record_id: int):
        if record_id not in self.index:
            raise ValueError(f"ไม่พบ ID {record_id}")
        offset = self.index.pop(record_id)
        # ตั้ง is_deleted=1 ที่ระเบียนนี้ โดยไม่เปลี่ยนข้อมูลอื่น
        with open(self.path, 'r+b') as f:
            f.seek(offset)
            data = f.read(self.size)
            rec = list(struct.unpack(self.fmt, data))
            rec[0] = 1  # is_deleted=1
            f.seek(offset)
            f.write(struct.pack(self.fmt, *rec))
        self.free_offsets.append(offset)

    def iter_active(self):
        """วนอ่านเฉพาะระเบียนที่ไม่ถูกลบ"""
        with open(self.path, 'rb') as f:
            offset = 0
            while True:
                chunk = f.read(self.size)
                if not chunk or len(chunk) < self.size:
                    break
                rec = struct.unpack(self.fmt, chunk)
                if rec[0] == 0:  # is_deleted==0
                    yield offset, rec
                offset += self.size

    def stats(self):
        total_slots = 0
        deleted = 0
        active = 0
        with open(self.path, 'rb') as f:
            while True:
                chunk = f.read(self.size)
                if not chunk or len(chunk) < self.size:
                    break
                total_slots += 1
                rec = struct.unpack(self.fmt, chunk)
                if rec[0] == 1:
                    deleted += 1
                else:
                    active += 1
        return {
            'active': active,
            'deleted': deleted,
            'holes': deleted,   # ช่องว่าง = deleted
            'total_slots': total_slots
        }

# --------------------------
# ตัวช่วย pack/unpack ของแต่ละไฟล์
# --------------------------
def pack_customer(is_deleted, cid, name, addr, brand, model, tel):
    return struct.pack(
        CUS_FMT,
        is_deleted,
        cid,
        to_fixed_bytes(name, 12),
        to_fixed_bytes(addr, 24),
        to_fixed_bytes(brand, 12),
        to_fixed_bytes(model, 16),
        to_fixed_bytes(tel, 12),
    )

def unpack_customer(rec):
    _, cid, name, addr, brand, model, tel = rec
    return {
        'customer_id': cid,
        'name': from_fixed_bytes(name),
        'address': from_fixed_bytes(addr),
        'brand': from_fixed_bytes(brand),
        'model': from_fixed_bytes(model),
        'tel': from_fixed_bytes(tel),
    }

def pack_notebook(is_deleted, nid, brand, serial, rel, price, status):
    return struct.pack(
        NB_FMT,
        is_deleted,
        nid,
        to_fixed_bytes(brand, 12),
        to_fixed_bytes(serial, 16),
        rel,
        float(price),
        status
    )

def unpack_notebook(rec):
    _, nid, brand, serial, rel, price, status = rec
    return {
        'notebook_id': nid,
        'brand': from_fixed_bytes(brand),
        'serial_num': from_fixed_bytes(serial),
        'rel': rel,
        'price': price,
        'status': status  # 1=stock, 0=sold out
    }

def pack_soldout(is_deleted, sid, nid, cid, name, sold_date, status):
    return struct.pack(
        SO_FMT,
        is_deleted,
        sid,
        nid,
        cid,
        to_fixed_bytes(name, 12),
        to_fixed_bytes(sold_date, 12),
        status
    )

def unpack_soldout(rec):
    _, sid, nid, cid, name, sold_date, status = rec
    return {
        'sold_out_id': sid,
        'notebook_id': nid,
        'customer_id': cid,
        'name': from_fixed_bytes(name),
        'soldout_date': from_fixed_bytes(sold_date),
        'status': status  # 1=instock, 0=soldout (ตามสเปคไฟล์)
    }

# --------------------------
# ตัวจัดการทั้งสามแฟ้ม
# --------------------------
cus_db = FixedRecordFile(CUS_FILE, CUS_FMT, CUS_SIZE, 'customer_id')
nb_db  = FixedRecordFile(NB_FILE,  NB_FMT,  NB_SIZE,  'notebook_id')
so_db  = FixedRecordFile(SO_FILE,  SO_FMT,  SO_SIZE,  'sold_out_id')

# เก็บประวัติการทำงานใน session
activity_log = []  # list[str]

def log_action(msg: str):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line)
    activity_log.append(line)
    # จำกัดความยาว log ล่าสุด
    if len(activity_log) > 200:
        del activity_log[:len(activity_log)-200]

# --------------------------
# Action: Add / Update / Delete / View / Report
# --------------------------

# ---- ลูกค้า ----
def add_customer():
    cid = input_int("ระบุ customer_id (int): ", allow_zero=False, positive_only=True)
    name = input_fixed_str("ชื่อ (<=12 bytes): ", 12)
    addr = input_fixed_str("ที่อยู่ (<=24 bytes): ", 24)
    brand = input_fixed_str("แบรนด์ (<=12 bytes): ", 12)
    model = input_fixed_str("รุ่น (<=16 bytes): ", 16)
    tel = input_fixed_str("โทร (<=12 bytes): ", 12)
    packed = pack_customer(0, cid, name, addr, brand, model, tel)
    cus_db.add(packed, cid)
    log_action(f"Add Customer id={cid}, name={name}")

def update_customer():
    cid = input_int("ระบุ customer_id ที่ต้องการแก้ไข: ", allow_zero=False, positive_only=True)
    offset, rec = cus_db.get(cid)
    if rec is None:
        print("** ไม่พบข้อมูล **")
        return
    data = unpack_customer(rec)
    print("ข้อมูลเดิม:", data)
    name = input_fixed_str(f"ชื่อ [{data['name']}]: ", 12) or data['name']
    addr = input_fixed_str(f"ที่อยู่ [{data['address']}]: ", 24) or data['address']
    brand = input_fixed_str(f"แบรนด์ [{data['brand']}]: ", 12) or data['brand']
    model = input_fixed_str(f"รุ่น [{data['model']}]: ", 16) or data['model']
    tel = input_fixed_str(f"โทร [{data['tel']}]: ", 12) or data['tel']
    packed = pack_customer(0, cid, name, addr, brand, model, tel)
    cus_db.update(cid, packed)
    log_action(f"Update Customer id={cid}")

def delete_customer():
    cid = input_int("ระบุ customer_id ที่ต้องการลบ: ", allow_zero=False, positive_only=True)
    cus_db.delete(cid)
    log_action(f"Delete Customer id={cid}")

def view_customer_menu():
    print("\n-- ดูข้อมูลลูกค้า --")
    print("1) ดูรายการเดียว (by id)")
    print("2) ดูทั้งหมด")
    print("3) ดูแบบกรอง (by brand)")
    print("4) สถิติโดยสรุป")
    print("0) กลับเมนูหลัก")
    choice = input("เลือก: ").strip()
    if choice == '1':
        cid = input_int("ระบุ customer_id: ", allow_zero=False, positive_only=True)
        offset, rec = cus_db.get(cid)
        if rec is None:
            print("** ไม่พบข้อมูล **")
            return
        print(unpack_customer(rec))
    elif choice == '2':
        for _, rec in cus_db.iter_active():
            print(unpack_customer(rec))
    elif choice == '3':
        brand = input("ระบุแบรนด์ที่ต้องการกรอง: ").strip()
        for _, rec in cus_db.iter_active():
            d = unpack_customer(rec)
            if d['brand'].lower() == brand.lower():
                print(d)
    elif choice == '4':
        s = cus_db.stats()
        print("สรุปลูกค้า:", s)

# ---- โน้ตบุ๊ก ----
def add_notebook():
    nid = input_int("ระบุ notebook_id (int): ", allow_zero=False, positive_only=True)
    brand = input_fixed_str("แบรนด์ (<=12 bytes): ", 12)
    serial = input_fixed_str("ซีเรียล (<=16 bytes): ", 16)
    rel = input_int("ปี/รุ่น (rel:int): ", allow_zero=True, positive_only=False)
    price = input_float("ราคา (float): ", positive_only=True)
    status = input_status("สถานะสินค้า 1=stock, 0=sold out")
    packed = pack_notebook(0, nid, brand, serial, rel, price, status)
    nb_db.add(packed, nid)
    log_action(f"Add Notebook id={nid}, brand={brand}, status={status}")

def update_notebook():
    nid = input_int("ระบุ notebook_id ที่ต้องการแก้ไข: ", allow_zero=False, positive_only=True)
    offset, rec = nb_db.get(nid)
    if rec is None:
        print("** ไม่พบข้อมูล **")
        return
    data = unpack_notebook(rec)
    print("ข้อมูลเดิม:", data)
    brand = input_fixed_str(f"แบรนด์ [{data['brand']}]: ", 12) or data['brand']
    serial = input_fixed_str(f"ซีเรียล [{data['serial_num']}]: ", 16) or data['serial_num']
    rel = input_int(f"rel [{data['rel']}]: ", allow_zero=True, positive_only=False)
    price_in = input(f"ราคา [{data['price']}]: ").strip()
    price = float(price_in) if price_in else data['price']
    status_in = input(f"สถานะ (1=stock,0=sold) [{data['status']}]: ").strip()
    status = int(status_in) if status_in in ('0', '1') else data['status']
    packed = pack_notebook(0, nid, brand, serial, rel, price, status)
    nb_db.update(nid, packed)
    log_action(f"Update Notebook id={nid}")

def delete_notebook():
    nid = input_int("ระบุ notebook_id ที่ต้องการลบ: ", allow_zero=False, positive_only=True)
    nb_db.delete(nid)
    log_action(f"Delete Notebook id={nid}")

def view_notebook_menu():
    print("\n-- ดูข้อมูลโน้ตบุ๊ก --")
    print("1) ดูรายการเดียว (by id)")
    print("2) ดูทั้งหมด")
    print("3) ดูแบบกรอง (brand/status/ช่วงราคา)")
    print("4) สถิติโดยสรุป (รวม stock/sold out)")
    print("0) กลับเมนูหลัก")
    choice = input("เลือก: ").strip()
    if choice == '1':
        nid = input_int("ระบุ notebook_id: ", allow_zero=False, positive_only=True)
        offset, rec = nb_db.get(nid)
        if rec is None:
            print("** ไม่พบข้อมูล **")
            return
        print(unpack_notebook(rec))
    elif choice == '2':
        for _, rec in nb_db.iter_active():
            print(unpack_notebook(rec))
    elif choice == '3':
        print("กรอง: 1=brand, 2=status, 3=ช่วงราคา")
        g = input("เลือกตัวกรอง: ").strip()
        if g == '1':
            brand = input("ระบุแบรนด์: ").strip()
            for _, rec in nb_db.iter_active():
                d = unpack_notebook(rec)
                if d['brand'].lower() == brand.lower():
                    print(d)
        elif g == '2':
            st = input_status("สถานะที่ต้องการ (1=stock,0=sold)")
            for _, rec in nb_db.iter_active():
                d = unpack_notebook(rec)
                if d['status'] == st:
                    print(d)
        elif g == '3':
            pmin = input_float("ราคา MIN: ", positive_only=True)
            pmax = input_float("ราคา MAX: ", positive_only=True)
            if pmin > pmax:
                pmin, pmax = pmax, pmin
            for _, rec in nb_db.iter_active():
                d = unpack_notebook(rec)
                if pmin <= d['price'] <= pmax:
                    print(d)
    elif choice == '4':
        s = nb_db.stats()
        stock = 0
        sold = 0
        for _, rec in nb_db.iter_active():
            d = unpack_notebook(rec)
            if d['status'] == 1:
                stock += 1
            else:
                sold += 1
        print("สรุปโน้ตบุ๊ก:", s, "| stock=", stock, "sold_out=", sold)

# ---- รายการขาย ----
def add_soldout():
    sid = input_int("sold_out_id: ", allow_zero=False, positive_only=True)
    nid = input_int("notebook_id: ", allow_zero=False, positive_only=True)
    cid = input_int("customer_id: ", allow_zero=False, positive_only=True)
    name = input_fixed_str("Name Customer: ", 12)
    sold_date = input_fixed_str("Sold date: ", 12)
    status = input_status("สถานะ 1=instock, 0=soldout (ตามสเปคไฟล์)")
    packed = pack_soldout(0, sid, nid, cid, name, sold_date, status)
    so_db.add(packed, sid)

    # อัปเดตสถานะโน้ตบุ๊กตามการขาย — ใช้ offset ที่ได้จาก nb_db.get()
    try:
        off, nbrec = nb_db.get(nid)
        if nbrec is not None:
            nbdata = unpack_notebook(nbrec)
            # เก็บค่า is_deleted ถ้ามี (fallback=0)
            is_deleted = nbdata.get('is_deleted', 0)
            packed_nb = pack_notebook(is_deleted,
                                      nbdata['notebook_id'],
                                      nbdata['brand'],
                                      nbdata['serial_num'],
                                      nbdata['rel'],
                                      nbdata['price'],
                                      status)
            nb_db.update(off, packed_nb)   # <-- ใช้ offset แทน id
            log_action(f"Notebook id={nid} status updated to {status} due to sale")
        else:
            print("** Warning: ไม่พบ notebook เพื่ออัปเดตสถานะ **")
    except Exception as e:
        print("** Warning: ไม่สามารถอัปเดตสถานะโน้ตบุ๊กได้:", e)

    log_action(f"Add Soldout id={sid}, nid={nid}, cid={cid}")

def update_soldout():
    sid = input_int("ระบุ sold_out_id ที่ต้องการแก้ไข: ", allow_zero=False, positive_only=True)
    offset, rec = so_db.get(sid)
    if rec is None:
        print("** ไม่พบข้อมูล **")
        return
    data = unpack_soldout(rec)
    print("ข้อมูลเดิม:", data)
    nid = input_int(f"notebook_id [{data['notebook_id']}]: ", allow_zero=False, positive_only=True)
    cid = input_int(f"customer_id [{data['customer_id']}]: ", allow_zero=False, positive_only=True)
    name = input_fixed_str(f"ชื่อลูกค้า [{data['name']}]: ", 12) or data['name']
    sold_date = input_fixed_str(f"วันที่ขาย [{data['soldout_date']}]: ", 12) or data['soldout_date']
    st_in = input(f"สถานะ (1/0) [{data['status']}]: ").strip()
    status = int(st_in) if st_in in ('0', '1') else data['status']
    packed = pack_soldout(0, sid, nid, cid, name, sold_date, status)
    so_db.update(sid, packed)

    # อัปเดตสถานะโน้ตบุ๊ก ให้สอดคล้องกับ record การขายนี้ — ใช้ offset ของ notebook
    try:
        off, nbrec = nb_db.get(nid)
        if nbrec is not None:
            nbdata = unpack_notebook(nbrec)
            is_deleted = nbdata.get('is_deleted', 0)
            packed_nb = pack_notebook(is_deleted,
                                      nbdata['notebook_id'],
                                      nbdata['brand'],
                                      nbdata['serial_num'],
                                      nbdata['rel'],
                                      nbdata['price'],
                                      status)
            nb_db.update(off, packed_nb)   # <-- ใช้ offset แทน id
            log_action(f"Notebook id={nid} status updated to {status} due to soldout update")
    except Exception as e:
        print("** Warning: ไม่สามารถอัปเดตสถานะโน้ตบุ๊กได้:", e)

    log_action(f"Update Soldout id={sid}")

def delete_soldout():
    sid = input_int("ระบุ sold_out_id ที่ต้องการลบ: ", allow_zero=False, positive_only=True)
    so_db.delete(sid)
    log_action(f"Delete SoldOut id={sid}")

def view_soldout_menu():
    print("\n-- ดูข้อมูลการขาย --")
    print("1) ดูรายการเดียว (by id)")
    print("2) ดูทั้งหมด")
    print("3) ดูแบบกรอง (by วันที่ขาย หรือสถานะ)")
    print("4) สถิติโดยสรุป")
    print("0) กลับเมนูหลัก")
    choice = input("เลือก: ").strip()
    if choice == '1':
        sid = input_int("ระบุ sold_out_id: ", allow_zero=False, positive_only=True)
        offset, rec = so_db.get(sid)
        if rec is None:
            print("** ไม่พบข้อมูล **")
            return
        print(unpack_soldout(rec))
    elif choice == '2':
        for _, rec in so_db.iter_active():
            print(unpack_soldout(rec))
    elif choice == '3':
        print("กรอง: 1=วันที่ขาย, 2=สถานะ")
        g = input("เลือกตัวกรอง: ").strip()
        if g == '1':
            date_str = input("ระบุวันที่ (เช่น 2025-10-01): ").strip()
            for _, rec in so_db.iter_active():
                d = unpack_soldout(rec)
                if d['soldout_date'] == date_str:
                    print(d)
        elif g == '2':
            st = input_status("สถานะที่ต้องการ (1=instock,0=soldout)")
            for _, rec in so_db.iter_active():
                d = unpack_soldout(rec)
                if d['status'] == st:
                    print(d)
    elif choice == '4':
        s = so_db.stats()
        instock = soldout = 0
        for _, rec in so_db.iter_active():
            d = unpack_soldout(rec)
            if d['status'] == 1:
                instock += 1
            else:
                soldout += 1
        print("สรุปการขาย:", s, "| instock=", instock, "soldout=", soldout)
# --------------------------
# ฟังก์ชันช่วยสำหรับทำตาราง ASCII + เวลาเขตไทย
# --------------------------
def _tz_offset_str():
    """คืนค่าออฟเซ็ตโซนเวลาเป็นรูปแบบ +HH:MM/-HH:MM จากระบบปัจจุบัน"""
    import time as _time
    if _time.localtime().tm_isdst and _time.daylight:
        offset_sec = -_time.altzone
    else:
        offset_sec = -_time.timezone
    sign = '+' if offset_sec >= 0 else '-'
    offset_sec = abs(offset_sec)
    hh = offset_sec // 3600
    mm = (offset_sec % 3600) // 60
    return f"{sign}{hh:02d}:{mm:02d}"

def _render_table(headers, rows, aligns=None):
    """
    headers: list[(ชื่อคอลัมน์, ความกว้าง)]
    rows   : list[list[str]] (ต้องมีจำนวนคอลัมน์ตรงกับ headers)
    aligns : list['l'|'r'] ความยาวเท่ากับจำนวนคอลัมน์ ถ้าไม่ระบุจะชิดซ้ายทั้งหมด
    """
    if not rows:
        return "(No active records)"
    if aligns is None:
        aligns = ['l'] * len(headers)

    def border():
        return '+' + '+'.join('-' * w for _, w in headers) + '+'

    def fmt_cell(val, w, align='l'):
        s = str(val)
        if len(s) > w:
            s = s[:w]
        return s.rjust(w) if align == 'r' else s.ljust(w)

    # Header row
    lines = [border()]
    head = '|' + '|'.join(fmt_cell(h, w, 'l') for h, w in headers) + '|'
    lines.append(head)
    lines.append(border())

    # Data rows
    for r in rows:
        line = '|' + '|'.join(
            fmt_cell(v, headers[i][1], aligns[i] if i < len(aligns) else 'l')
            for i, v in enumerate(r)
        ) + '|'
        lines.append(line)
    lines.append(border())
    return '\n'.join(lines)

# ---- รายงาน ----
def build_report_text():
    # เวลา (แสดงออฟเซ็ตโซนเวลา เช่น +07:00)
    now_str = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ({_tz_offset_str()})"

    # สถิติรวมจากไฟล์
    nb_s = nb_db.stats()

    # สร้างแมปลูกค้า (id -> record) จาก cus_db
    cus_map = {}
    for _, crec in cus_db.iter_active():
        cd = unpack_customer(crec)
        cus_map[cd['customer_id']] = cd

    # สร้างแมป notebook_id -> customer_id จาก so_db (รายการขาย)
    nb_to_cid = {}
    for _, srec in so_db.iter_active():
        sd = unpack_soldout(srec)
        # ถ้าขายหลายครั้ง จะใช้รายการล่าสุดที่วนเจอ (ไฟล์เรียงตามการเพิ่ม)
        nb_to_cid[sd['notebook_id']] = sd['customer_id']

    # รวบรวมข้อมูลสำหรับตาราง และคำนวณสรุป
    nb_rows = []
    prices = []
    brand_counter = Counter()
    stock = sold = 0

    for _, rec in nb_db.iter_active():
        d = unpack_notebook(rec)

        status_txt = 'Active' if d['status'] == 1 else 'Sold Out'
        sold_txt = 'Yes' if d['status'] == 0 else 'No'
        if d['status'] == 1:
            stock += 1
        else:
            sold += 1

        prices.append(d['price'])
        brand_counter[d['brand']] += 1

        # หาข้อมูลลูกค้าที่เกี่ยวข้อง (ถ้ามี)
        cid = nb_to_cid.get(d['notebook_id'], '')
        tel = ''
        addr = ''
        if cid:
            cust = cus_map.get(cid)
            if cust:
                tel = cust.get('tel', '')
                addr = cust.get('address', '')

        # เปลี่ยนลำดับคอลัมน์: NotebookID, CusID, Tel, Address, Brand, Serial, Year, Price, Status, Sold
        nb_rows.append([
            d['notebook_id'],
            cid,
            tel,
            addr,
            d['brand'],
            d['serial_num'],
            d['rel'],
            f"{d['price']:.2f}",
            status_txt,
            sold_txt,
        ])

    # สถิติราคา (เฉพาะ Active)
    if prices:
        p_min = min(prices)
        p_max = max(prices)
        p_avg = sum(prices) / len(prices)
    else:
        p_min = p_max = p_avg = None

    # ส่วนหัวรายงาน
    header_lines = [
        "Notebook Store – Summary Report (Sample)",
        f"Generated At: {now_str}",
        "App Version: 1.0",
        "Endianness: Little-Endian",
        "Encoding: UTF-8 (fixed-length)",
        "",
    ]

    # ตารางหลัก (NotebookID ตามด้วย CusID, Tel, Address)
    nb_headers = [
        ("NotebookID", 12),
        ("CusID", 8),
        ("Tel", 12),
        ("Address", 24),
        ("Brand", 12),
        ("Model", 16),
        ("Year", 6),
        ("Price (THB)", 12),
        ("Status", 10),
        ("Sold", 6),
    ]
    nb_aligns = ['r', 'r', 'l', 'l', 'l', 'l', 'r', 'r', 'l', 'l']
    nb_table = _render_table(nb_headers, nb_rows, nb_aligns)

    # สรุป (เฉพาะ Active)
    summary_lines = [
        "",
        "Summary (เฉพาะสถานะ Active)",
        f"– Total Notebooks (records): {nb_s['total_slots']}",
        f"– Active Notebooks: {nb_s['active']}",
        f"– Deleted Notebooks: {nb_s['deleted']}",
        f"– Currently Sold: {sold}",
        f"– Available Now: {stock}",
        "",
        "Price Statistics (THB, Active only):",
        f"– Min : {p_min:.2f}" if p_min is not None else "– Min : N/A",
        f"– Max : {p_max:.2f}" if p_max is not None else "– Max : N/A",
        f"– Avg : {p_avg:.2f}" if p_avg is not None else "– Avg : N/A",
        "",
        "Notebooks by Brand (Active only):",
    ]
    if brand_counter:
        for brand, cnt in sorted(brand_counter.items()):
            summary_lines.append(f"– {brand} : {cnt}")
    else:
        summary_lines.append("– (none)")

    # กิจกรรมล่าสุด
    activity_block = ["", "Recent Activities:"]
    last_n = activity_log[-50:]
    if last_n:
        activity_block.extend(last_n)
    else:
        activity_block.append("(no activities in this session)")

    parts = []
    parts.extend(header_lines)
    parts.append(nb_table)
    parts.extend(summary_lines)
    parts.extend(activity_block)
    parts.append("")

    return "\n".join(parts)
# ...existing code...
# filepath: /home/pkp/Notebook_Report/cpro.py
# ...existing code...
def build_report_text():
    # เวลา (แสดงออฟเซ็ตโซนเวลา เช่น +07:00)
    now_str = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ({_tz_offset_str()})"

    # สถิติรวมจากไฟล์
    nb_s = nb_db.stats()

    # สร้างแมปลูกค้า (id -> record) จาก cus_db
    cus_map = {}
    for _, crec in cus_db.iter_active():
        cd = unpack_customer(crec)
        cus_map[cd['customer_id']] = cd

    # สร้างแมป notebook_id -> customer_id จาก so_db (รายการขาย)
    nb_to_cid = {}
    for _, srec in so_db.iter_active():
        sd = unpack_soldout(srec)
        nb_to_cid[sd['notebook_id']] = sd['customer_id']

    # DEBUG: แสดงแม็ปในรายงาน (ลบออกเมื่อเสร็จ)
    debug_lines = []
    debug_lines.append(f"DEBUG: nb_to_cid = {nb_to_cid}")
    debug_lines.append(f"DEBUG: cus_map keys = {list(cus_map.keys())}")

    # รวบรวมข้อมูลสำหรับตาราง และคำนวณสรุป
    nb_rows = []
    prices = []
    brand_counter = Counter()
    stock = sold = 0

    for _, rec in nb_db.iter_active():
        d = unpack_notebook(rec)

        status_txt = 'Active' if d['status'] == 1 else 'Sold Out'
        sold_txt = 'Yes' if d['status'] == 0 else 'No'
        if d['status'] == 1:
            stock += 1
        else:
            sold += 1

        prices.append(d['price'])
        brand_counter[d['brand']] += 1

        # หาข้อมูลลูกค้าที่เกี่ยวข้อง (ถ้ามี)
        cid = nb_to_cid.get(d['notebook_id'], '')
        tel = ''
        addr = ''
        if cid:
            cust = cus_map.get(cid)
            if cust:
                tel = cust.get('tel', '')
                addr = cust.get('address', '')

        # เปลี่ยนลำดับคอลัมน์: NotebookID, CusID, Tel, Address, Brand, Serial, Year, Price, Status, Sold
        nb_rows.append([
            d['notebook_id'],
            cid,
            tel,
            addr,
            d['brand'],
            d['serial_num'],
            d['rel'],
            f"{d['price']:.2f}",
            status_txt,
            sold_txt,
        ])

    # สถิติราคา (เฉพาะ Active)
    if prices:
        p_min = min(prices)
        p_max = max(prices)
        p_avg = sum(prices) / len(prices)
    else:
        p_min = p_max = p_avg = None

    # ส่วนหัวรายงาน
    header_lines = [
        "Notebook Store – Summary Report (Sample)",
        f"Generated At: {now_str}",
        "App Version: 1.0",
        "Endianness: Little-Endian",
        "Encoding: UTF-8 (fixed-length)",
        "",
    ]

    # ตารางหลัก (NotebookID ตามด้วย CusID, Tel, Address)
    nb_headers = [
        ("NotebookID", 12),
        ("CusID", 8),
        ("Tel", 12),
        ("Address", 24),
        ("Brand", 12),
        ("Serial", 16),
        ("Year", 6),
        ("Price (THB)", 12),
        ("Status", 10),
        ("Sold", 6),
    ]
    nb_aligns = ['r', 'r', 'l', 'l', 'l', 'l', 'r', 'r', 'l', 'l']
    nb_table = _render_table(nb_headers, nb_rows, nb_aligns)

    # สรุป (เฉพาะ Active)
    summary_lines = [
        "",
        "Summary (เฉพาะสถานะ Active)",
        f"– Total Notebooks (records): {nb_s['total_slots']}",
        f"– Active Notebooks: {nb_s['active']}",
        f"– Deleted Notebooks: {nb_s['deleted']}",
        f"– Currently Sold: {sold}",
        f"– Available Now: {stock}",
        "",
        "Price Statistics (THB, Active only):",
        f"– Min : {p_min:.2f}" if p_min is not None else "– Min : N/A",
        f"– Max : {p_max:.2f}" if p_max is not None else "– Max : N/A",
        f"– Avg : {p_avg:.2f}" if p_avg is not None else "– Avg : N/A",
        "",
        "Notebooks by Brand (Active only):",
    ]
    if brand_counter:
        for brand, cnt in sorted(brand_counter.items()):
            summary_lines.append(f"– {brand} : {cnt}")
    else:
        summary_lines.append("– (none)")

    # กิจกรรมล่าสุด
    activity_block = ["", "Recent Activities:"]
    last_n = activity_log[-50:]
    if last_n:
        activity_block.extend(last_n)
    else:
        activity_block.append("(no activities in this session)")

    parts = []
    parts.extend(header_lines)
    parts.append(nb_table)
    parts.extend(summary_lines)
    parts.extend(activity_block)
    parts.append("") 
    parts.extend(debug_lines)   # <-- ให้บล็อก debug แสดงในท้ายรายงาน
    parts.append("")

    return "\n".join(parts)
# --------------------------
# เมนูหลัก
# --------------------------
def main_menu():
    while True:
        print("\n=== NOTEBOOK STORE MENU (1…n) ===")
        print("1) Add (เพิ่ม)")
        print("2) Update (แก้ไข)")
        print("3) Delete (ลบ)")
        print("4) View (ดู)")
        print("5) Report (.txt) (สร้างรายงาน)")
        print("0) Exit")
        choice = input("เลือกเมนู: ").strip()

        if choice == '1':
            print("\n-- Add --")
            print("1) Customer")
            print("2) Notebook")
            print("3) SoldOut")
            print("0) กลับ")
            c = input("เลือก: ").strip()
            if c == '1': add_customer()
            elif c == '2': add_notebook()
            elif c == '3': add_soldout()

        elif choice == '2':
            print("\n-- Update --")
            print("1) Customer")
            print("2) Notebook")
            print("3) SoldOut")
            print("0) กลับ")
            c = input("เลือก: ").strip()
            if c == '1': update_customer()
            elif c == '2': update_notebook()
            elif c == '3': update_soldout()

        elif choice == '3':
            print("\n-- Delete --")
            print("1) Customer")
            print("2) Notebook")
            print("3) SoldOut")
            print("0) กลับ")
            c = input("เลือก: ").strip()
            if c == '1': delete_customer()
            elif c == '2': delete_notebook()
            elif c == '3': delete_soldout()

        elif choice == '4':
            print("\n-- View --")
            print("1) Customer")
            print("2) Notebook")
            print("3) SoldOut")
            print("0) กลับ")
            c = input("เลือก: ").strip()
            if c == '1': view_customer_menu()
            elif c == '2': view_notebook_menu()
            elif c == '3': view_soldout_menu()

        elif choice == '5':
            report_text = build_report_text()
            with open(REPORT_FILE, 'w', encoding='utf-8') as rf:
                rf.write(report_text)
            log_action(f"Report written: {REPORT_FILE}")
            print(f"Report saved to {REPORT_FILE}")

        elif choice == '0':
            print("ลาก่อน")
            break

        else:
            print("** เมนูไม่ถูกต้อง กรุณาลองใหม่ **")

if __name__ == '__main__':
    main_menu()