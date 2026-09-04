import logging
import sys
import mcp_text2sql

from mcp.server.mcpserver import MCPServer 

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("text2sql-server")

try:
    mcp = MCPServer(
        name = "mcp-text2sql",
    )
    logger.info("MCP server initialized successfully")
except Exception as e:
        err_msg = f"Error: {str(e)}"
        logger.info(f"{err_msg}")

######################################
# Text2SQL
######################################
@mcp.tool()
def generate_query(question: str) -> str:
    """
    Generate an SQL statement to query the database.
    question: Information to retrieve from the database
    return: Generated SQL statement
    """
    return mcp_text2sql.generate_query(question)

@mcp.tool()
def execute_query(sql: str) -> str:
    """
    Execute SQL against the database and return the relevant information.
    sql: SQL statement to execute
    return: Result of the SQL execution
    """
    return mcp_text2sql.execute_query(sql)

if __name__ =="__main__":
    mcp.run(transport="stdio")




