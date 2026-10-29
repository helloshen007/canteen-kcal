import hashlib
import hmac
import secrets
import time

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

COOKIE = 'canteen_session'
bearer = HTTPBearer(auto_error=False)


def password_hash(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 260_000).hex()
    return f'pbkdf2_sha256$260000${salt}${digest}'


def password_matches(password, encoded):
    try:
        algorithm, iterations, salt, expected = encoded.split('$')
        if algorithm != 'pbkdf2_sha256':
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(iterations)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def token_for(user, secret, hours):
    return jwt.encode({'sub':user.id, 'ver':user.token_version, 'iat':int(time.time()),
                       'exp':int(time.time()) + hours * 3600, 'iss':'canteen-kcal'}, secret, algorithm='HS256')


def db_session(request: Request):
    with request.app.state.sessions() as session:
        yield session


def current_user(request: Request, authorization: HTTPAuthorizationCredentials | None = Depends(bearer),
                 session=Depends(db_session)):
    from web.database import User
    token = authorization.credentials if authorization else request.cookies.get(COOKIE)
    try:
        data = jwt.decode(token or '', request.app.state.secret, algorithms=['HS256'], issuer='canteen-kcal',
                          options={'require':['sub','ver','exp','iat','iss']})
        user = session.get(User, data['sub'])
        if user is None or user.token_version != data['ver']:
            raise ValueError('revoked token')
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise HTTPException(401, '请先登录') from None
    return user
