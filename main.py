import sys
from PyQt5.QtWidgets import QApplication, QWidget, QPushButton, QHBoxLayout, QVBoxLayout
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor



#       MODEL ZBIORNIKA

class Zbiornik:
    # trzymamy tylko to co potrzebne: nazwa, ile max, ile jest, jaka temp
    def __init__(self, nazwa, pojemnosc_l, objetosc_l, temperatura_c):
        self.nazwa = nazwa
        self.pojemnosc_l = pojemnosc_l
        self.objetosc_l = objetosc_l
        self.temperatura_c = temperatura_c

    def poziom(self):
        # zabezpieczenie przed dzieleniem przez 0
        if self.pojemnosc_l <= 0:
            return 0.0
        return self.objetosc_l / self.pojemnosc_l

    def wolne_miejsce(self):
        # ile jeszcze brakuje do pełna
        wolne = self.pojemnosc_l - self.objetosc_l
        if wolne < 0:
            wolne = 0.0
        return wolne

    def dodaj_wode(self, litry, temperatura_wejscia_c):
        # na minusy nie pozwalamy
        if litry < 0:
            litry = 0.0

        # nie dolewamy więcej niż się zmieści
        wolne = self.wolne_miejsce()
        if litry > wolne:
            litry = wolne

        # jak nic nie dolewamy, to nie ma o czym gadać
        if litry <= 0:
            return 0.0

        # jeśli zbiornik jest pusty temperatura od razu staje się temp wejścia
        if self.objetosc_l == 0:
            self.objetosc_l = litry
            self.temperatura_c = temperatura_wejscia_c
            return litry

        # mieszanie temperatur: średnia ważona
        nowa_obj = self.objetosc_l + litry
        nowa_temp = (self.temperatura_c * self.objetosc_l + temperatura_wejscia_c * litry) / nowa_obj

        self.objetosc_l = nowa_obj
        self.temperatura_c = nowa_temp
        return litry

    # ile litrów zabierasz ze zbiornika (i jaka jest temp tej wody)
    def pobierz_wode(self, litry):
        if litry < 0:
            litry = 0.0

        # nie da się zabrać więcej niż jest
        if litry > self.objetosc_l:
            litry = self.objetosc_l

        self.objetosc_l -= litry
        return litry, self.temperatura_c



#       MODEL PROCESU

class ModelProcesu:
    """
    Cała logika procesu:
    """

    def __init__(self):
        # zbiorniki startowe wartości pojemność objętość temperatura
        self.zb_t1 = Zbiornik("T1", 200.0, 40.0, 30.0)
        self.zb_t2 = Zbiornik("T2", 180.0, 30.0, 25.0)
        self.zb_t3 = Zbiornik("T3", 180.0, 30.0, 25.0)
        self.zb_t4 = Zbiornik("T4", 250.0, 40.0, 25.0)

        # dopływ do T1 zawór
        self.zawor_wejscie_proc = 100
        self.doplyw_max_lps = 6.0
        self.temperatura_doplywu_c = 15.0

        # grzałka w T1
        self.grzalka_wlaczona = True
        self.grzalka_moc = 0.40

        # pompa na powrocie T3 -> T1
        self.pompa_wlaczona = True
        self.pompa_lpm = 120.0

        # progi króćców przelewowych
        self.prog_przelewu_12 = 0.70
        self.prog_przelewu_23 = 0.70
        self.prog_przelewu_3 = 0.70

        # prosta "fizyka"
        self.wsp_przelewu = 0.25  # im większy, tym szybciej przelewa
        self.odplyw_max_lps = 6.0  # maks odpływ z T4

        # czas i animacja
        self.czas_symulacji_s = 0.0
        self.faza_animacji = 0.0

        # dane do wykresu T4
        self.historia_czasu = []
        self.historia_obj_t4 = []
        self.historia_temp_t4 = []

        # alarmy
        self.alarmy = []

        # przepływy do animacji (L/s)
        self.przeplyw_in = 0.0
        self.przeplyw_12 = 0.0
        self.przeplyw_23 = 0.0
        self.przeplyw_31 = 0.0
        self.przeplyw_34 = 0.0
        self.przeplyw_out = 0.0

    def _przelew_grawitacyjny(self, zbiornik_zrodlowy, zbiornik_docelowy, prog, czas_kroku_s):
        #  jak czas kroku = 0 to nic się nie rusza
        if czas_kroku_s <= 0:
            return 0.0

        # próg zamieniamy na litry
        prog_litry = prog * zbiornik_zrodlowy.pojemnosc_l

        # nadmiar = ile jest ponad króćcem
        nadmiar = zbiornik_zrodlowy.objetosc_l - prog_litry
        if nadmiar < 0:
            nadmiar = 0.0

        # jak nie ma nadmiaru to nie przelewa
        if nadmiar <= 1e-9:
            return 0.0

        # jak docelowy nie ma miejsca, to też nie przelewa
        if zbiornik_docelowy.wolne_miejsce() <= 1e-9:
            return 0.0

        # prędkość przelewu rośnie wraz z nadmiarem
        q_lps = self.wsp_przelewu * nadmiar
        litry = q_lps * czas_kroku_s

        # ograniczenia max tyle ile jest nadmiaru i max tyle ile wolnego miejsca
        if litry > nadmiar:
            litry = nadmiar

        wolne = zbiornik_docelowy.wolne_miejsce()
        if litry > wolne:
            litry = wolne

        # przenosimy wodę ubywa z źródła przybywa w docelowym
        zbiornik_zrodlowy.objetosc_l -= litry
        zbiornik_docelowy.dodaj_wode(litry, zbiornik_zrodlowy.temperatura_c)

        return litry / czas_kroku_s  # zwracamy żeby animacja miała info

    def krok(self, czas_kroku_s):
        """Jeden krok symulacji """
        self.czas_symulacji_s += czas_kroku_s
        self.faza_animacji = (self.faza_animacji + czas_kroku_s * 1.5) % 1.0

        # 1) Dopływ do T1 zawór
        q_in = self.doplyw_max_lps * (self.zawor_wejscie_proc / 100.0)  # L/s
        litry_in = q_in * czas_kroku_s
        litry_in = self.zb_t1.dodaj_wode(litry_in, self.temperatura_doplywu_c)
        self.przeplyw_in = (litry_in / czas_kroku_s) if czas_kroku_s > 0 else 0.0

        # 2) Grzanie T1
        if self.grzalka_wlaczona and self.zb_t1.objetosc_l > 1e-9:
            # celowo proste im większa moc i czas tym rośnie temp
            self.zb_t1.temperatura_c += (8.0 * self.grzalka_moc * czas_kroku_s) / max(1.0, self.zb_t1.objetosc_l / 50.0)

        # 3) Przelewy T1->T2->T3
        self.przeplyw_12 = self._przelew_grawitacyjny(self.zb_t1, self.zb_t2, self.prog_przelewu_12, czas_kroku_s)
        self.przeplyw_23 = self._przelew_grawitacyjny(self.zb_t2, self.zb_t3, self.prog_przelewu_23, czas_kroku_s)

        # 4) Nadmiar z T3 część do T1 (pompa), reszta do T4
        self.przeplyw_31 = 0.0
        self.przeplyw_34 = 0.0

        prog3_litry = self.prog_przelewu_3 * self.zb_t3.pojemnosc_l
        nadmiar3 = self.zb_t3.objetosc_l - prog3_litry
        if nadmiar3 < 0:
            nadmiar3 = 0.0

        if nadmiar3 > 1e-9 and czas_kroku_s > 0:
            q_over = self.wsp_przelewu * nadmiar3  # chce wypłynąć
            litry_total = q_over * czas_kroku_s  # ile w tym kroku

            if litry_total > nadmiar3:
                litry_total = nadmiar3

            # pompa T3->T1 (L/min -> L/s)
            pompa_lps = (self.pompa_lpm / 60.0) if self.pompa_wlaczona else 0.0

            litry_do_t1 = pompa_lps * czas_kroku_s
            if litry_do_t1 > litry_total:
                litry_do_t1 = litry_total

            wolne1 = self.zb_t1.wolne_miejsce()
            if litry_do_t1 > wolne1:
                litry_do_t1 = wolne1

            # reszta grawitacyjnie do T4
            litry_do_t4 = litry_total - litry_do_t1
            wolne4 = self.zb_t4.wolne_miejsce()
            if litry_do_t4 > wolne4:
                litry_do_t4 = wolne4

            # jeśli T4 pełne to reszta zostaje w T3
            litry_real = litry_do_t1 + litry_do_t4
            self.zb_t3.objetosc_l -= litry_real

            if litry_do_t1 > 0:
                self.zb_t1.dodaj_wode(litry_do_t1, self.zb_t3.temperatura_c)
            if litry_do_t4 > 0:
                self.zb_t4.dodaj_wode(litry_do_t4, self.zb_t3.temperatura_c)

            self.przeplyw_31 = litry_do_t1 / czas_kroku_s
            self.przeplyw_34 = litry_do_t4 / czas_kroku_s

        # 5) Odpływ z dołu T4
        q_out = self.odplyw_max_lps * max(0.0, min(1.0, self.zb_t4.poziom()))
        litry_out = q_out * czas_kroku_s
        litry_out, _temp = self.zb_t4.pobierz_wode(litry_out)
        self.przeplyw_out = (litry_out / czas_kroku_s) if czas_kroku_s > 0 else 0.0

        # 6) Alarmy
        self.alarmy = []
        for zb in [self.zb_t1, self.zb_t2, self.zb_t3, self.zb_t4]:
            if zb.poziom() > 0.90:
                self.alarmy.append(f"{zb.nazwa}: poziom >90%")
            if zb.poziom() < 0.10:
                self.alarmy.append(f"{zb.nazwa}: poziom <10%")
            if zb.temperatura_c > 80.0:
                self.alarmy.append(f"{zb.nazwa}: temp >80C")

        # 7) Trend T4 co 0.5 s dopisujemy punkt
        if (len(self.historia_czasu) == 0) or (self.czas_symulacji_s - self.historia_czasu[-1] >= 0.5):
            self.historia_czasu.append(self.czas_symulacji_s)
            self.historia_obj_t4.append(self.zb_t4.objetosc_l)
            self.historia_temp_t4.append(self.zb_t4.temperatura_c)


#         WIDOK

class EkranWizualizacji(QWidget):
    def __init__(self, model_procesu):
        super().__init__()
        self.model = model_procesu
        self.tryb_widoku = 0  # 0=instalacja, 1=wykres

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        szer = self.width()
        wys = self.height()

        # tło
        p.fillRect(0, 0, szer, wys, QBrush(QColor("#111827")))

        # pasek alarmów
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#0B1220")))
        p.drawRect(0, 0, szer, 34)
        p.setPen(QPen(QColor("#E5E7EB"), 1))

        if len(self.model.alarmy) == 0:
            txt = "ALARMY: brak"
        else:
            txt = "ALARMY: " + ", ".join(self.model.alarmy[:3])
            if len(self.model.alarmy) > 3:
                txt += "..."
        p.drawText(10, 23, txt)

        # status taki szybki opis co jest ustawione
        pompa_pokaz = self.model.pompa_lpm if self.model.pompa_wlaczona else 0.0
        status = (
            f"Zawor IN: {self.model.zawor_wejscie_proc}%   "
            f"Grzalka: {int(self.model.grzalka_moc * 100)}%   "
            f"Pompa(T3->T1): {pompa_pokaz:.0f} L/min   "
            f"Odplyw T4(dol): {self.model.przeplyw_out:.1f} L/s"
        )
        p.drawText(10, 55, status)

        if self.tryb_widoku == 1:
            self.rysuj_wykres_t4(p, szer, wys)
        else:
            self.rysuj_instalacje(p, szer, wys)

    def rysuj_wykres_t4(self, p, szer, wys):
        gx, gy, gw, gh = 60, 80, szer - 80, wys - 140
        p.setPen(QPen(QColor("#9CA3AF"), 2))
        p.drawRect(gx, gy, gw, gh)

        p.setPen(QPen(QColor("#E5E7EB"), 1))
        p.drawText(60, 75, "Wykres T4: zielony=poziom[L], pomaranczowy=temp[C]")

        t = self.model.historia_czasu
        lv = self.model.historia_obj_t4
        tp = self.model.historia_temp_t4

        if len(t) < 2:
            p.drawText(gx + 10, gy + 25, "Zbieram dane...")
            return

        t0 = t[0]
        t1 = t[-1]
        if t1 <= t0:
            t1 = t0 + 1.0

        def na_x(tv):
            return gx + int(gw * (tv - t0) / (t1 - t0))

        def na_y(v, lo, hi):
            return gy + gh - int(gh * (v - lo) / (hi - lo))

        # poziom zielony
        p.setPen(QPen(QColor("#34D399"), 2))
        for i in range(len(t) - 1):
            p.drawLine(
                na_x(t[i]), na_y(lv[i], 0, self.model.zb_t4.pojemnosc_l),
                na_x(t[i + 1]), na_y(lv[i + 1], 0, self.model.zb_t4.pojemnosc_l)
            )

        # temp pomarańczowy
        p.setPen(QPen(QColor("#F59E0B"), 2))
        for i in range(len(t) - 1):
            p.drawLine(
                na_x(t[i]), na_y(tp[i], 20, 100),
                na_x(t[i + 1]), na_y(tp[i + 1], 20, 100)
            )

    def rysuj_instalacje(self, p, szer, wys):
        # pomoc prostokąt zbiornika w procentach ekranu
        def prostokat_zbiornika(x):
            return int(szer * x), int(wys * 0.18), int(szer * 0.16), int(wys * 0.60)

        r1 = prostokat_zbiornika(0.06)
        r2 = prostokat_zbiornika(0.30)
        r3 = prostokat_zbiornika(0.54)
        r4 = prostokat_zbiornika(0.78)

        # y króćca przelewowego na podstawie progu
        def y_krociec(R, prog):
            x, y, w, h = R
            iy = y + 6
            ih = h - 12
            return int(iy + (1.0 - prog) * ih)

        y12 = y_krociec(r1, self.model.prog_przelewu_12)
        y23 = y_krociec(r2, self.model.prog_przelewu_23)
        y3o = y_krociec(r3, self.model.prog_przelewu_3)

        y_gora = int(wys * 0.12)

        x1, y1, w1, h1 = r1
        x2, y2, w2, h2 = r2
        x3, y3, w3, h3 = r3
        x4, y4, w4, h4 = r4

        t1R = (x1 + w1, y12)
        t2L = (x2, y12)

        t2R = (x2 + w2, y23)
        t3L = (x3, y23)

        t3R = (x3 + w3, y3o)
        t4L = (x4, y3o)

        zawor = (int(szer * 0.04), y12)
        z_lewo = (int(szer * 0.01), y12)
        z_in = (x1, y12)

        J = (int((t3R[0] + t4L[0]) / 2), y3o)  # punkt rozdziału

        powrot_wej = (x1, int(y1 + 16))
        pompa_xy = (J[0] - 30, y_gora)

        y4_dol = int(y4 + h4 - 6)
        odplyw_start = (x4 + int(w4 * 0.70), y4_dol)
        odplyw_koniec = (int(szer * 0.99), int(wys * 0.95))

        sciezki = {
            "in":  [z_lewo, zawor, z_in],
            "12":  [t1R, t2L],
            "23":  [t2R, t3L],
            "3J":  [t3R, J],
            "J4":  [J, t4L],
            "J1":  [J, (J[0], y_gora), (powrot_wej[0], y_gora), powrot_wej],
            "out": [odplyw_start, (odplyw_start[0], int(wys * 0.95)), odplyw_koniec],
        }

        # rury
        p.setPen(QPen(QColor("#9CA3AF"), 8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for path in sciezki.values():
            for i in range(len(path) - 1):
                p.drawLine(path[i][0], path[i][1], path[i + 1][0], path[i + 1][1])

        # punkt rozdziału

        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#E5E7EB")))
        p.drawEllipse(J[0] - 5, J[1] - 5, 10, 10)

        # animacja kropek

        faza = self.model.faza_animacji
        p.setPen(QPen(QColor("#34D399"), 1))
        p.setBrush(QBrush(QColor("#34D399")))

        def animuj(path):
            for i in range(len(path) - 1):
                xA, yA = path[i]
                xB, yB = path[i + 1]
                x = int(xA + (xB - xA) * faza)
                y = int(yA + (yB - yA) * faza)
                p.drawEllipse(x - 4, y - 4, 8, 8)

        if self.model.przeplyw_in > 0.01:
            animuj(sciezki["in"])
        if self.model.przeplyw_12 > 0.01:
            animuj(sciezki["12"])
        if self.model.przeplyw_23 > 0.01:
            animuj(sciezki["23"])
        if (self.model.przeplyw_31 + self.model.przeplyw_34) > 0.01:
            animuj(sciezki["3J"])
            if self.model.przeplyw_34 > 0.01:
                animuj(sciezki["J4"])
            if self.model.przeplyw_31 > 0.01:
                animuj(sciezki["J1"])
        if self.model.przeplyw_out > 0.01:
            animuj(sciezki["out"])

        # zawór (Z)

        p.setPen(QPen(QColor("#E5E7EB"), 2))
        p.setBrush(QBrush(QColor("#60A5FA") if self.model.zawor_wejscie_proc > 0 else QColor("#6B7280")))
        p.drawRect(zawor[0] - 12, zawor[1] - 12, 24, 24)
        p.setPen(QPen(QColor("#111827"), 2))
        p.drawText(zawor[0] - 7, zawor[1] + 6, "Z")
        p.setPen(QPen(QColor("#E5E7EB"), 1))
        p.drawText(zawor[0] - 18, zawor[1] - 18, f"{self.model.zawor_wejscie_proc}%")

        # pompa (P)

        p.setPen(QPen(QColor("#E5E7EB"), 2))
        p.setBrush(QBrush(QColor("#10B981") if (self.model.pompa_wlaczona and self.model.pompa_lpm > 0) else QColor("#6B7280")))
        p.drawEllipse(pompa_xy[0] - 18, pompa_xy[1] - 18, 36, 36)
        p.setPen(QPen(QColor("#111827"), 2))
        p.drawText(pompa_xy[0] - 12, pompa_xy[1] + 6, "P")
        p.setPen(QPen(QColor("#E5E7EB"), 1))
        pompa_pokaz = self.model.pompa_lpm if self.model.pompa_wlaczona else 0.0
        p.drawText(pompa_xy[0] - 22, pompa_xy[1] - 22, f"{pompa_pokaz:.0f}")

        # grzałka (H) jako mały klocek na dole

        hx = int(szer * 0.12)
        hy = int(wys * 0.85)
        p.setPen(QPen(QColor("#E5E7EB"), 2))
        p.setBrush(QBrush(QColor("#F59E0B") if (self.model.grzalka_wlaczona and self.model.grzalka_moc > 0.01) else QColor("#6B7280")))
        p.drawRect(hx - 16, hy - 12, 32, 24)
        p.setPen(QPen(QColor("#111827"), 2))
        p.drawText(hx - 9, hy + 6, "H")
        p.setPen(QPen(QColor("#E5E7EB"), 1))
        p.drawText(hx - 18, hy + 34, f"{int(self.model.grzalka_moc * 100)}%")

        # zbiorniki i opisy na dole

        for R, zb in [(r1, self.model.zb_t1), (r2, self.model.zb_t2), (r3, self.model.zb_t3), (r4, self.model.zb_t4)]:
            x, y, w, h = R

            p.setPen(QPen(QColor("#E5E7EB"), 2))
            p.setBrush(QBrush(QColor("#1F2937")))
            p.drawRoundedRect(x, y, w, h, 10, 10)

            ix = x + 6
            iy = y + 6
            iw = w - 12
            ih = h - 12

            fill = zb.poziom()
            if fill < 0:
                fill = 0.0
            if fill > 1:
                fill = 1.0

            fh = int(ih * fill)
            fy = iy + (ih - fh)

            # kolor zależny od temperatury

            tn = (zb.temperatura_c - 20.0) / 60.0
            if tn < 0:
                tn = 0.0
            if tn > 1:
                tn = 1.0
            col = QColor(int(80 + 160 * tn), int(140 - 60 * tn), int(220 - 180 * tn))

            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(col))
            p.drawRoundedRect(ix, fy, iw, fh, 8, 8)

            p.setPen(QPen(QColor("#E5E7EB"), 1))
            opis = f"{zb.nazwa}  {zb.objetosc_l:5.1f}L  {fill*100:3.0f}%  {zb.temperatura_c:4.1f}C"
            p.drawText(x, y + h + 8, w, 45, Qt.AlignHCenter | Qt.AlignTop, opis)



#        OKNO

class OknoGlowne(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Wizualizacja")

        self.model = ModelProcesu()
        self.ekran = EkranWizualizacji(self.model)

        # krok czasowy symulacji

        self.czas_kroku_s = 0.05

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tykniecie)

        # przyciski

        b_start = QPushButton("Start")
        b_stop = QPushButton("Stop")
        b_tryb = QPushButton("Instalacja/wykresy")

        b_z0 = QPushButton("Zawor IN ON/OFF")
        b_zp = QPushButton("Zawor IN +")
        b_zm = QPushButton("Zawor IN -")

        b_p0 = QPushButton("Pompa ON/OFF")
        b_pp = QPushButton("Pompa +")
        b_pm = QPushButton("Pompa -")

        b_h0 = QPushButton("Grzalka ON/OFF")
        b_hp = QPushButton("Grzalka +")
        b_hm = QPushButton("Grzalka -")

        # akcje

        b_start.clicked.connect(lambda: self.timer.start(int(self.czas_kroku_s * 1000)))
        b_stop.clicked.connect(self.timer.stop)
        b_tryb.clicked.connect(self.zmien_tryb)

        b_z0.clicked.connect(self.zawor_toggle)
        b_zp.clicked.connect(self.zawor_plus)
        b_zm.clicked.connect(self.zawor_minus)

        b_p0.clicked.connect(self.pompa_toggle)
        b_pp.clicked.connect(self.pompa_plus)
        b_pm.clicked.connect(self.pompa_minus)

        b_h0.clicked.connect(self.grzalka_toggle)
        b_hp.clicked.connect(self.grzalka_plus)
        b_hm.clicked.connect(self.grzalka_minus)

        # układ przycisków

        r1 = QHBoxLayout()
        for w in [b_start, b_stop, b_tryb, b_z0, b_zp, b_zm]:
            r1.addWidget(w)

        r2 = QHBoxLayout()
        for w in [b_p0, b_pp, b_pm, b_h0, b_hp, b_hm]:
            r2.addWidget(w)

        lay = QVBoxLayout()
        lay.addLayout(r1)
        lay.addLayout(r2)
        lay.addWidget(self.ekran)
        self.setLayout(lay)

        self.resize(1100, 650)

    #        obsługa GUI


    def zmien_tryb(self):
        self.ekran.tryb_widoku = 1 - self.ekran.tryb_widoku
        self.ekran.update()

    def zawor_toggle(self):
        self.model.zawor_wejscie_proc = 0 if self.model.zawor_wejscie_proc > 0 else 100

    def zawor_plus(self):
        self.model.zawor_wejscie_proc += 10
        if self.model.zawor_wejscie_proc > 100:
            self.model.zawor_wejscie_proc = 100

    def zawor_minus(self):
        self.model.zawor_wejscie_proc -= 10
        if self.model.zawor_wejscie_proc < 0:
            self.model.zawor_wejscie_proc = 0

    def pompa_toggle(self):
        self.model.pompa_wlaczona = not self.model.pompa_wlaczona

    def pompa_plus(self):
        self.model.pompa_lpm += 30
        if self.model.pompa_lpm > 600:
            self.model.pompa_lpm = 600

    def pompa_minus(self):
        self.model.pompa_lpm -= 30
        if self.model.pompa_lpm < 0:
            self.model.pompa_lpm = 0

    def grzalka_toggle(self):
        self.model.grzalka_wlaczona = not self.model.grzalka_wlaczona

    def grzalka_plus(self):
        self.model.grzalka_moc += 0.05
        if self.model.grzalka_moc > 1.0:
            self.model.grzalka_moc = 1.0

    def grzalka_minus(self):
        self.model.grzalka_moc -= 0.05
        if self.model.grzalka_moc < 0.0:
            self.model.grzalka_moc = 0.0

    #         symulacja

    def tykniecie(self):
        self.model.krok(self.czas_kroku_s)
        self.ekran.update()



#           START

if __name__ == "__main__":
    app = QApplication(sys.argv)
    okno = OknoGlowne()
    okno.show()
    sys.exit(app.exec_())
