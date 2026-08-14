import sys
path = "/Users/koushikviswandha/Desktop/Xevyte_Connect-main/employee-login-portal/src/pages/Sidebar.js"
with open(path, "r") as f:
    content = f.read()

injection = """      {/* Standalone AI Agent (Redirects to standalone frontend) */}
      <h3>
        <a href="http://localhost:5174" target="_blank" rel="noopener noreferrer" className="side" style={getLinkStyle("/Agent")}>
          <span className="sidebar-link-text" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
              <i className="bi bi-robot" style={{ color: '#06b6d4' }}></i> AI Agent
            </span>
            <i className="bi bi-box-arrow-up-right standalone-chevron" style={{ fontSize: '0.75rem' }}></i>
          </span>
        </a>
      </h3>

"""

if injection in content:
    content = content.replace(injection, "")
    with open(path, "w") as f:
        f.write(content)
    print("Link removed successfully!")
else:
    print("Link not found!")
