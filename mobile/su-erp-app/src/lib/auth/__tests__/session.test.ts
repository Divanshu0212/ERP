import { roleHome, useSession } from '../session';

jest.mock('../../api/auth', () => ({
  login: jest.fn(),
  logout: jest.fn(),
  fetchMe: jest.fn(),
}));
jest.mock('../../device/identity', () => ({
  getDeviceId: jest.fn(async () => 'dev-1'),
  getPlatform: jest.fn(() => 'android'),
  getModelName: jest.fn(() => 'Pixel 7'),
}));
jest.mock('../storage', () => ({
  readRefreshToken: jest.fn(async () => null),
  clearRefreshToken: jest.fn(async () => {}),
  saveRefreshToken: jest.fn(async () => {}),
}));

const api = jest.requireMock('../../api/auth');

beforeEach(() => {
  useSession.setState({ status: 'loading', user: null });
  jest.clearAllMocks();
});

test('signIn stores the user and marks the session signed in', async () => {
  api.login.mockResolvedValue({ access: 'a', refresh: 'r' });
  api.fetchMe.mockResolvedValue({
    user_code: 'STU-001',
    email: 'student@example.com',
    role: 'student',
    tenant: 'tenant-uuid',
  });

  await useSession.getState().signIn('alpha', 'student@example.com', 'pw');

  const state = useSession.getState();
  expect(state.status).toBe('signed-in');
  expect(state.user?.role).toBe('student');
});

test('signIn sends the device identity with the credentials', async () => {
  api.login.mockResolvedValue({ access: 'a', refresh: 'r' });
  api.fetchMe.mockResolvedValue({
    user_code: 'STU-001',
    email: 'student@example.com',
    role: 'student',
    tenant: 't',
  });

  await useSession.getState().signIn('alpha', 'student@example.com', 'pw');

  expect(api.login).toHaveBeenCalledWith(
    expect.objectContaining({ device_id: 'dev-1', platform: 'android' }),
  );
});

test('signOut clears the user', async () => {
  api.logout.mockResolvedValue(undefined);
  useSession.setState({
    status: 'signed-in',
    user: { user_code: 'STU-001', email: 'e', role: 'student', tenant: 't' },
  });

  await useSession.getState().signOut();

  expect(useSession.getState().status).toBe('signed-out');
  expect(useSession.getState().user).toBeNull();
});

test('restore with no stored refresh token lands signed out', async () => {
  await useSession.getState().restore();
  expect(useSession.getState().status).toBe('signed-out');
});

test('roleHome maps each app role to its shell', () => {
  expect(roleHome('student')).toBe('/(student)');
  expect(roleHome('warden')).toBe('/(warden)');
  expect(roleHome('driver')).toBe('/(driver)');
  expect(roleHome('canteen_owner')).toBe('/(canteen-owner)');
});

test('roleHome sends web-only roles to the unsupported screen', () => {
  expect(roleHome('admin')).toBe('/unsupported-role');
  expect(roleHome('superadmin')).toBe('/unsupported-role');
});
