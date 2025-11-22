import pymysql

pymysql.install_as_MySQLdb()

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

