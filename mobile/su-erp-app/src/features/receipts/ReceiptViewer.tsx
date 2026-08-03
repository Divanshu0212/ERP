import { Modal, View } from 'react-native';
import { WebView } from 'react-native-webview';

import { Press } from '@/components/Press';
import { Body, Button, Screen, Title } from '@/components/ui';

/**
 * Renders a receipt PDF inside the app.
 *
 * Handing the file to an ACTION_VIEW intent makes Android show an app chooser
 * — this device offers twelve PDF handlers — which turns "view my receipt"
 * into "pick an app first". Android's WebView has no built-in PDF renderer
 * either, so the bytes are drawn onto a canvas with pdf.js.
 *
 * The PDF is passed as base64 rather than a URL because the endpoint needs a
 * bearer token the WebView does not carry.
 */
function viewerHtml(base64: string): string {
  return `<!doctype html>
<html>
  <head>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
      body { margin: 0; background: #f4f6f9; }
      canvas { display: block; width: 100%; margin: 0 0 12px; }
      #error { padding: 24px; font: 15px system-ui, sans-serif; color: #5b6472; }
    </style>
  </head>
  <body>
    <div id="pages"></div>
    <div id="error" hidden>Could not display this receipt.</div>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
    <script>
      function fail() {
        document.getElementById('error').hidden = false;
      }

      try {
        pdfjsLib.GlobalWorkerOptions.workerSrc =
          'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

        var raw = atob('${base64}');
        var bytes = new Uint8Array(raw.length);
        for (var i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);

        pdfjsLib.getDocument({ data: bytes }).promise.then(function (pdf) {
          var container = document.getElementById('pages');

          for (var n = 1; n <= pdf.numPages; n++) {
            pdf.getPage(n).then(function (page) {
              // Render at 2x for a sharp result on a high-density screen.
              var viewport = page.getViewport({ scale: 2 });
              var canvas = document.createElement('canvas');
              canvas.width = viewport.width;
              canvas.height = viewport.height;
              container.appendChild(canvas);
              page.render({ canvasContext: canvas.getContext('2d'), viewport: viewport });
            });
          }
        }).catch(fail);
      } catch (e) {
        fail();
      }
    </script>
  </body>
</html>`;
}

export function ReceiptViewer({
  base64,
  onClose,
  onShare,
}: {
  base64: string | null;
  onClose: () => void;
  onShare: () => void;
}) {
  if (!base64) return null;

  return (
    <Modal visible animationType="slide" onRequestClose={onClose}>
      <Screen>
        <View className="flex-row items-center justify-between border-b border-surface-border px-4 py-3">
          <Title>Receipt</Title>
          <Press onPress={onClose} accessibilityRole="button" accessibilityLabel="Close receipt">
            <View className="min-h-touch min-w-touch items-center justify-center">
              <Body>Close</Body>
            </View>
          </Press>
        </View>

        <WebView
          originWhitelist={['*']}
          source={{ html: viewerHtml(base64) }}
          style={{ flex: 1, backgroundColor: '#f4f6f9' }}
        />

        <View className="border-t border-surface-border px-4 pb-6 pt-3">
          <Button label="Share or save" tone="quiet" onPress={onShare} />
        </View>
      </Screen>
    </Modal>
  );
}
