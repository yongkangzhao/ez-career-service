from mcp.server.fastmcp import FastMCP

mcp = FastMCP("user_profile")

@mcp.tool()
def get_resume():
    return open("resume.md", "r").read()

def get_resume_path():
    return "/Users/aiden/projects/ez-career-service/Resume Aiden Zhao.pdf"

if __name__ == "__main__":
    mcp.run(transport='stdio')