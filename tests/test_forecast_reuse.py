import unittest,sys
sys.path.insert(0,"scripts")
from forecast_reuse import extend_loss,share_issuer
class ForecastReuseTest(unittest.TestCase):
    def sample(self):
        a={"currency":"KRW","account_id":"ifrs-full_ProfitLoss","annual_receipt":"20260301000001","quarter_receipt":"20261101000001","estimate":-20,"prior_year_actual":-100}
        b={**a,"quarter_receipt":"20260801000001","estimate":-50}
        return {"ticker":"005930","values":{},"raw_current":{"op":a,"net":a},"raw_previous":{"net":b}}
    def test_loss_reuse(self):
        r=extend_loss(self.sample())
        self.assertGreater(r["values"]["operating_profit_forecast_growth"]["value"],0)
        self.assertGreater(r["values"]["earnings_forecast_revision"]["value"],0)
    def test_identity(self):
        r=self.sample()
        models,links=share_issuer({"005930":r},{"005930":{"corp_code":"00126380"}},[{"ticker":"005935","parent":"005930","parent_corp":"00126380","category":"known_preferred_share"}],{"005935":"005930"})
        self.assertEqual(links,{"005935":"005930"})
        self.assertEqual(models["005935"]["ticker"],"005935")
        self.assertEqual(models["005935"]["issuer_forecast_reference"],"005930")
    def test_reject_wrong_corp(self):
        models,links=share_issuer({"005930":self.sample()},{"005930":{"corp_code":"other"}},[{"ticker":"005935","parent":"005930","parent_corp":"00126380","category":"known_preferred_share"}],{"005935":"005930"})
        self.assertNotIn("005935",models)
        self.assertFalse(links)
if __name__=="__main__":unittest.main()
