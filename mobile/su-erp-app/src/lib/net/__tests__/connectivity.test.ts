import {
  notifyReachable,
  notifyUnreachable,
  startConnectivityWatch,
  useConnectivity,
} from '../connectivity';

let listener: ((state: { isConnected: boolean | null }) => void) | null = null;

jest.mock('@react-native-community/netinfo', () => ({
  addEventListener: jest.fn((cb) => {
    listener = cb;
    return () => {
      listener = null;
    };
  }),
}));
jest.mock('../../offline/queue', () => ({
  replay: jest.fn(async () => ({ sent: 0, dropped: 0, failed: 0 })),
}));

const { replay } = jest.requireMock('../../offline/queue');

beforeEach(() => {
  useConnectivity.setState({ online: true });
  replay.mockClear();
});

test('going offline flips the store', () => {
  startConnectivityWatch();
  listener?.({ isConnected: false });
  expect(useConnectivity.getState().online).toBe(false);
});

test('coming back online replays the queue', async () => {
  startConnectivityWatch();
  listener?.({ isConnected: false });
  listener?.({ isConnected: true });
  await Promise.resolve();
  expect(replay).toHaveBeenCalled();
});

test('staying online does not replay', async () => {
  startConnectivityWatch();
  listener?.({ isConnected: true });
  await Promise.resolve();
  expect(replay).not.toHaveBeenCalled();
});

// Regression: found on-device. The radio never dropped, so NetInfo never fired
// and the queue sat undrained even after the server came back.
test('reaching the server again replays a queue filled while it was unreachable', async () => {
  startConnectivityWatch();

  notifyUnreachable();
  notifyReachable();
  await Promise.resolve();

  expect(replay).toHaveBeenCalled();
});

test('a plain successful request does not replay on its own', async () => {
  startConnectivityWatch();

  notifyReachable();
  await Promise.resolve();

  expect(replay).not.toHaveBeenCalled();
});
