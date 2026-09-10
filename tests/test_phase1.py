import pytest
from app import create_app
from app.extensions import db
from app.models.user import User


@pytest.fixture
def app():
    """Create and configure a clean testing app instance."""
    app = create_app("testing")

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    """Test client for the app."""
    return app.test_client()


def test_app_starts(app):
    """Test that the application starts and testing config is active."""
    assert app is not None
    assert app.config["TESTING"] is True


def test_homepage(client):
    """Test that the landing page renders with status code 200."""
    response = client.get("/")
    assert response.status_code == 200
    assert b"SmartSupport" in response.data
    assert b"AI-Powered Customer Support" in response.data


def test_api_health(client):
    """Test that GET /api/health returns healthy JSON with 200 status."""
    response = client.get("/api/health")
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data["status"] == "healthy"
    assert json_data["database"] == "connected"


def test_user_registration(client, app):
    """Test standard user registration and password hashing."""
    response = client.post("/register", data={
        "name": "Jane Doe",
        "email": "jane@example.com",
        "password": "password123",
        "confirm_password": "password123",
        "role": "customer"
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"Account created successfully" in response.data

    with app.app_context():
        user = User.query.filter_by(email="jane@example.com").first()
        assert user is not None
        assert user.name == "Jane Doe"
        assert user.role == "customer"
        assert user.password_hash != "password123"
        assert user.check_password("password123") is True
        assert user.check_password("wrongpassword") is False


def test_duplicate_registration_handling(client):
    """Test that registering duplicate email returns friendly 400 error."""
    # First registration
    client.post("/register", data={
        "name": "First User",
        "email": "duplicate@example.com",
        "password": "password123",
        "confirm_password": "password123",
        "role": "customer"
    })

    # Second registration with same email
    response = client.post("/register", data={
        "name": "Second User",
        "email": "duplicate@example.com",
        "password": "password123",
        "confirm_password": "password123",
        "role": "customer"
    })

    assert response.status_code == 400
    assert b"already exists" in response.data


def test_user_login_and_logout(client):
    """Test login with valid credentials and subsequent logout."""
    # Register user first
    client.post("/register", data={
        "name": "Login User",
        "email": "loginuser@example.com",
        "password": "securepassword",
        "confirm_password": "securepassword",
        "role": "customer"
    })

    # Login
    login_res = client.post("/login", data={
        "email": "loginuser@example.com",
        "password": "securepassword"
    }, follow_redirects=True)

    assert login_res.status_code == 200
    assert b"Welcome back, Login User!" in login_res.data
    assert b"Customer Dashboard" in login_res.data

    # Logout
    logout_res = client.get("/logout", follow_redirects=True)
    assert logout_res.status_code == 200
    assert b"You have been securely logged out" in logout_res.data
    assert b"Sign in to your customer or support account" in logout_res.data


def test_invalid_login(client):
    """Test login with incorrect password returns 401."""
    # Register user
    client.post("/register", data={
        "name": "Test User",
        "email": "test@example.com",
        "password": "correctpassword",
        "confirm_password": "correctpassword",
        "role": "customer"
    })

    # Attempt login with wrong password
    response = client.post("/login", data={
        "email": "test@example.com",
        "password": "wrongpassword"
    })

    assert response.status_code == 401
    assert b"Invalid email or password" in response.data


def test_protected_customer_dashboard_redirect(client):
    """Test accessing customer dashboard without authentication redirects to login."""
    response = client.get("/dashboard")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_unauthorized_admin_access(client):
    """Test customer role attempting to access admin dashboard receives 403 Forbidden."""
    # Register and login customer
    client.post("/register", data={
        "name": "Normal Customer",
        "email": "customer@example.com",
        "password": "password123",
        "confirm_password": "password123",
        "role": "customer"
    })
    client.post("/login", data={
        "email": "customer@example.com",
        "password": "password123"
    })

    # Customer attempts to access /admin/dashboard
    response = client.get("/admin/dashboard")
    assert response.status_code == 403
    assert b"403" in response.data
    assert b"Access Denied" in response.data


def test_authorized_support_admin_access(client):
    """Test support/admin role can access admin dashboard."""
    # Register and login support agent
    client.post("/register", data={
        "name": "Support Agent",
        "email": "agent@example.com",
        "password": "password123",
        "confirm_password": "password123",
        "role": "support"
    })
    client.post("/login", data={
        "email": "agent@example.com",
        "password": "password123"
    })

    response = client.get("/admin/dashboard")
    assert response.status_code == 200
    assert b"Support &amp; Operations Center" in response.data


def test_404_error_handling(client):
    """Test that a non-existent route returns custom 404 page."""
    response = client.get("/non-existent-page-12345")
    assert response.status_code == 404
    assert b"404" in response.data
    assert b"Page Not Found" in response.data


def test_api_auth_endpoints(client):
    """Test JSON REST endpoints for auth."""
    # Register via API
    reg_res = client.post("/api/auth/register", json={
        "name": "API User",
        "email": "apiuser@example.com",
        "password": "password123",
        "role": "customer"
    })
    assert reg_res.status_code == 201
    user_data = reg_res.json.get("data") or reg_res.json.get("user")
    assert user_data["email"] == "apiuser@example.com"

    # Get /api/auth/me
    me_res = client.get("/api/auth/me")
    assert me_res.status_code == 200
    me_data = me_res.json.get("data") or me_res.json.get("user")
    assert me_data["name"] == "API User"

    # Logout via API
    logout_res = client.post("/api/auth/logout")
    assert logout_res.status_code == 200
