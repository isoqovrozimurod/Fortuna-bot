// 1. Barcha qatorlarni olish
let barchaQatorlar = Array.from(document.querySelectorAll('tr'));

// 3-ustun sanalarini olish
let sanalar = barchaQatorlar
    .map(tr => {
        let td = tr.querySelector('td:nth-child(3)');
        return td ? td.innerText.trim() : null;
    })
    .filter(text => text && /\d{2}\/\d{2}\/\d{4} \d{2}:\d{2}:\d{2}/.test(text));

// Sanalarni Date formatiga o'tkazish
let sanalarParsed = sanalar.map(s => {
    let [datePart, timePart] = s.split(' ');
    let [day, month, year] = datePart.split('/');
    return new Date(`${year}-${month}-${day}T${timePart}`);
});

// Sana diapazoni
let boshSana = new Date(Math.min(...sanalarParsed));
let oxirgiSana = new Date(Math.max(...sanalarParsed));

// Sana formatlash
function formatDate(date) {
    let d = String(date.getDate()).padStart(2, '0');
    let m = String(date.getMonth() + 1).padStart(2, '0');
    let y = date.getFullYear();
    return `${d}.${m}.${y}`;
}

// 7-ustundan kredit turlarini aniqlash
let kreditTurlar = Array.from(new Set(
    barchaQatorlar
        .map(tr => tr.querySelector('td:nth-child(7)'))
        .filter(td => td)
        .map(td => td.innerText.trim())
));

// Summalarni topish
let summalar = Array.from(document.querySelectorAll('td')).filter(td => {
    return td.innerText.includes(",00") &&
           !isNaN(parseFloat(td.innerText.replace(/\s/g, "").replace(",", ".")));
});

// Holatlar statistikasi (umumiy)
let holatStat = {
    berilgan: { soni: 0, summa: 0 },
    yopilgan: { soni: 0, summa: 0 },
    bekor: { soni: 0, summa: 0 }
};

// Xodimlar statistikasi (bekor qilinganni hisoblamaydi!)
let xodimlar = {};

// Summalarni o‘tish
summalar.forEach(td => {
    let qator = td.closest('tr');
    if (!qator) return;

    // Holatni olish
    let holatTd = qator.querySelector('td:nth-child(11)');
    let holatRaw = holatTd ? holatTd.innerText.trim().toLowerCase() : "";

    // Rus → O‘zbek tarjima
    let tarjima = {
        "выдано": "berilgan",
        "закрыта": "yopilgan",
        "отменена": "bekor qilingan"
    };

    let holat = tarjima[holatRaw] || holatRaw;
    let summa = parseFloat(td.innerText.replace(/\s/g, "").replace(",", "."));

    // 🔥 Holatlar umumiy statistikasi
    if (holat === "berilgan") {
        holatStat.berilgan.soni++;
        holatStat.berilgan.summa += summa;
    } else if (holat === "yopilgan") {
        holatStat.yopilgan.soni++;
        holatStat.yopilgan.summa += summa;
    } else if (holat === "bekor qilingan") {
        holatStat.bekor.soni++;
        holatStat.bekor.summa += summa;

        // ❗ Xodim statistikasi va umumiy hisobga kiritilmaydi
        return;
    } else {
        return;
    }

    // 🔥 Xodim statistikasi (bekorlar kirmaydi)
    let kreditTuri = qator.querySelector('td:nth-child(7)').innerText.trim();
    let xodim = qator.querySelector('td:nth-child(8)').innerText.trim();

    if (!xodimlar[xodim]) {
        xodimlar[xodim] = {
            jamiSumma: 0,
            jamiHisob: 0,
            turlar: {}
        };

        kreditTurlar.forEach(tur => {
            xodimlar[xodim].turlar[tur] = { soni: 0, summa: 0 };
        });
    }

    xodimlar[xodim].jamiSumma += summa;
    xodimlar[xodim].jamiHisob++;

    if (xodimlar[xodim].turlar[kreditTuri]) {
        xodimlar[xodim].turlar[kreditTuri].soni++;
        xodimlar[xodim].turlar[kreditTuri].summa += summa;
    }
});

// Umumiy statistika
let umumiyJami = Object.values(xodimlar).reduce((a, b) => a + b.jamiSumma, 0);
let umumiyHisob = Object.values(xodimlar).reduce((a, b) => a + b.jamiHisob, 0);

// Natijalar
console.log(`\n📅 Kreditlar davri: ${formatDate(boshSana)} - ${formatDate(oxirgiSana)}\n`);

for (let xodim in xodimlar) {
    let { jamiSumma, jamiHisob, turlar } = xodimlar[xodim];
    let foiz = (jamiSumma / umumiyJami) * 100;

    console.log(`\n👤 ${xodim}:`);
    console.log(`  💰 Jami summa: ${jamiSumma.toLocaleString('fr-FR')} so'm (${foiz.toFixed(2)}%)`);
    console.log(`  🧾 Jami kreditlar soni: ${jamiHisob} ta`);
    console.log(`  📌 Kredit turlari:`);

    for (let tur in turlar) {
        if (turlar[tur].soni > 0) {
            console.log(`    - ${tur}: ${turlar[tur].soni} ta, summa: ${turlar[tur].summa.toLocaleString('fr-FR')} so'm`);
        }
    }
}

console.log(`\n🔢 Umumiy kreditlar soni: ${umumiyHisob} ta`);
console.log(`📊 Umumiy kredit summasi: ${umumiyJami.toLocaleString('fr-FR')} so'm`);

// 🔥 Holatlar bo‘yicha umumiy statistika
console.log(`\n📌 Kredit holatlari statistikasi:`);
console.log(`  ✔️ Berilgan: ${holatStat.berilgan.soni} ta, summa: ${holatStat.berilgan.summa.toLocaleString('fr-FR')} so'm`);
console.log(`  🔒 Yopilgan: ${holatStat.yopilgan.soni} ta, summa: ${holatStat.yopilgan.summa.toLocaleString('fr-FR')} so'm`);
console.log(`  ❌ Bekor qilingan: ${holatStat.bekor.soni} ta, summa: ${holatStat.bekor.summa.toLocaleString('fr-FR')} so'm`);
