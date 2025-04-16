from mcp.server.fastmcp import FastMCP

mcp = FastMCP("user_profile")

@mcp.tool()
def get_resume():
    return open("resume.md", "r").read()


if __name__ == "__main__":
    mcp.run(transport='stdio')