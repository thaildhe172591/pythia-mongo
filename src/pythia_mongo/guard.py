"""The harness tier: what pythia-core's guard and install need to know
about MongoDB. The guard denies mongosh (and the legacy mongo shell) when it
would write around the gate, and mongoimport, mongorestore and mongofiles
always; reads through mongosh are left to the client's own prompt.

The patterns read a shell command for what it names, never for what it
means, so a write spelled in a way they do not list gets through, and a
read that merely mentions .drop( is denied. The gate behind them holds
either way (pythia-core's SECURITY.md).
"""
import pathlib

CLIENTS = r"mongosh|mongo|mongoimport|mongorestore|mongofiles"

# matched against the whole command, quoted JavaScript included
WRITE_SQL = "|".join((
    r"\.(insert|insertone|insertmany|update|updateone|updatemany|replaceone|remove|"
    r"delete|deleteone|deletemany|drop|dropindex|dropindexes|createindex|"
    r"createindexes|ensureindex|hideindex|unhideindex|renamecollection|"
    r"findoneandupdate|findoneandreplace|findoneanddelete|findandmodify|bulkwrite|"
    r"createcollection|createview|createsearchindex|dropsearchindex|"
    r"updatesearchindex|runcommand|admincommand|dropdatabase|createuser|dropuser|"
    r"updateuser|grantrolestouser|revokerolesfromuser|createrole|droprole)\s*\(",
    r"\$(out|merge)\b",                       # a pipeline that writes
    r"\bload\s*\(",                           # mongosh running a script file
    # a command document handed to a database's MCP tool
    r"[\"']?\b(insert|update|delete|findandmodify|collmod|create|drop|createindexes|"
    r"dropindexes|renamecollection|dropdatabase|createuser|applyops)[\"']?\s*:",
))

# matched with quoted text emptied: what the shell hands the client
SCRIPT = "|".join((
    r"(?-i:(^|\s)(-f\s*\S|--file(=|\s)))",    # mongosh -f / --file
    r"(^|\s)[^\s'\"]+\.[mc]?js(\s|$)",        # a script file as an argument
    r"(^|[^<])<(?![<(&])\s*\S",               # stdin from a file, not <<, <(
    r"\|\s*(\S*[/\\])?(mongosh|mongo)\b",     # a script piped into the shell
    r"\bmongo(import|restore|files)\b",       # each of these writes
))

# MongoDB's MCP servers name their tools by action, not by SQL
MCP_TOOLS = r"mongo"
MCP_WRITE_TOOLS = (r"^(insert|update|delete|drop|create|rename|replace|bulk)"
                   r"|[-_](insert|update|delete|drop|create|rename)")

TEMPLATE = {
    "default": "dev",
    "dev": {
        "host": "",
        "port": 27017,
        "database": "",
        "user": "",
        "password": "",
        "auth_source": "admin",
        "tls": False,
    },
}

SKILLS_DIR = pathlib.Path(__file__).resolve().parent / "skills"
