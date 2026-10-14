package app.stackupfinance.site;

import android.os.Bundle;
import android.webkit.CookieManager;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (getBridge() != null && getBridge().getWebView() != null) {
            CookieManager.getInstance().setAcceptThirdPartyCookies(
                getBridge().getWebView(),
                true
            );
        }
    }
}
