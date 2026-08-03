import type { RazorpayOrder, RazorpayProof } from '@api-types/index';
import { Modal, View } from 'react-native';
import { WebView } from 'react-native-webview';

import { Body, Button, Screen, Title } from '@/components/ui';

/**
 * Razorpay Checkout in a WebView.
 *
 * The official React Native SDK needs a custom dev build; Razorpay's web
 * checkout runs anywhere a WebView does, and react-native-webview ships with
 * Expo Go. The page below is a shell whose only job is to open the widget and
 * post the result back.
 *
 * SECURITY: what comes out of here is a claim, not a fact. The signature is
 * verified server-side against the key secret (see suerp_common
 * razorpay_gateway.verify_signature, called from PayView), and the key secret
 * never reaches this device — only the public key_id does. A tampered
 * postMessage cannot mark an invoice paid.
 */
function checkoutHtml(order: RazorpayOrder, description: string): string {
  const payload = JSON.stringify({
    key: order.key_id,
    order_id: order.order_id,
    amount: order.amount,
    currency: order.currency || 'INR',
    name: 'SU-ERP',
    description,
  });

  return `<!doctype html>
<html>
  <head><meta name="viewport" content="width=device-width, initial-scale=1" /></head>
  <body style="margin:0;background:#f4f6f9">
    <script src="https://checkout.razorpay.com/v1/checkout.js"></script>
    <script>
      function send(message) {
        window.ReactNativeWebView.postMessage(JSON.stringify(message));
      }

      var options = ${payload};

      options.handler = function (response) {
        send({
          type: 'success',
          razorpay_order_id: response.razorpay_order_id,
          razorpay_payment_id: response.razorpay_payment_id,
          razorpay_signature: response.razorpay_signature
        });
      };

      options.modal = {
        ondismiss: function () { send({ type: 'cancelled' }); },
        escape: false
      };

      try {
        var checkout = new Razorpay(options);
        checkout.on('payment.failed', function (response) {
          send({ type: 'failed', message: (response.error && response.error.description) || 'Payment failed.' });
        });
        checkout.open();
      } catch (e) {
        send({ type: 'failed', message: String(e) });
      }
    </script>
  </body>
</html>`;
}

export interface CheckoutResult {
  type: 'success' | 'cancelled' | 'failed';
  message?: string;
  proof?: RazorpayProof;
}

export function RazorpayCheckout({
  order,
  description,
  onDone,
}: {
  order: RazorpayOrder | null;
  description: string;
  onDone: (result: CheckoutResult) => void;
}) {
  if (!order) return null;

  // No key_id means the server has no Razorpay credentials and handed back a
  // simulated order. Opening a widget with an empty key would just fail, so
  // the flow falls through to the backend's simulated gateway instead.
  if (!order.key_id) {
    return (
      <Modal visible animationType="slide" onRequestClose={() => onDone({ type: 'cancelled' })}>
        <Screen>
          <View className="flex-1 justify-center gap-4 p-6">
            <Title>Test payment</Title>
            <Body muted>
              Razorpay is not configured on this server, so no card is charged. Continuing records
              the payment through the simulated gateway.
            </Body>
            <Button label="Continue" onPress={() => onDone({ type: 'success' })} />
            <Button label="Cancel" tone="quiet" onPress={() => onDone({ type: 'cancelled' })} />
          </View>
        </Screen>
      </Modal>
    );
  }

  return (
    <Modal visible animationType="slide" onRequestClose={() => onDone({ type: 'cancelled' })}>
      <Screen>
        <WebView
          originWhitelist={['*']}
          source={{ html: checkoutHtml(order, description), baseUrl: 'https://checkout.razorpay.com' }}
          onMessage={(event) => {
            try {
              const data = JSON.parse(event.nativeEvent.data);

              if (data.type === 'success') {
                onDone({
                  type: 'success',
                  proof: {
                    razorpay_order_id: data.razorpay_order_id,
                    razorpay_payment_id: data.razorpay_payment_id,
                    razorpay_signature: data.razorpay_signature,
                  },
                });
                return;
              }

              onDone({ type: data.type, message: data.message });
            } catch {
              onDone({ type: 'failed', message: 'Could not read the payment result.' });
            }
          }}
        />
      </Screen>
    </Modal>
  );
}
