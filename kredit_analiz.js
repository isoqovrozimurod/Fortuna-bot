// 1. Sana diapazonini 3-ustundan aniqlaymiz (indeks 2)
let barchaQatorlar = Array.from(document.querySelectorAll('tr'));

// 3-ustun sanalarini olish
let sanalar = barchaQatorlar
    .map(tr => {
        let td = tr.querySelector('td:nth-child(3)');
        return td ? td.innerText.trim() : null;
    })
    .filter(text => text && /\d{2}\/\d{2}\/\d{4} \d{2}:\d{2}:\d{2}/.test(text));

// Sanalarni Date obyektlariga aylantirish
let sanalarParsed = sanalar.map(s => {
    let [datePart, timePart] = s.split(' ');
    let [day, month, year] = datePart.split('/').map(num => num.padStart(2, '0'));
    return new Date(`${year}-${month}-${day}T${timePart}`);
});

let boshSana = new Date(Math.min(...sanalarParsed));
let oxirgiSana = new Date(Math.max(...sanalarParsed));

// Sana formatlash funksiyasi
function formatDate(date) {
    let d = date.getDate().toString().padStart(2, '0');
    let m = (date.getMonth() + 1).toString().padStart(2, '0');
    let y = date.getFullYear();
    return `${d}.${m}.${y}`;
}

// 2. Kredit turlarini aniqlash (7-ustun — td:nth-child(7))
let kreditTurlarSet = new Set(
    barchaQatorlar
        .map(tr => {
            let tds = tr.querySelectorAll('td');
            return tds.length >= 7 ? tds[6].innerText.trim() : null;
        })
        .filter(Boolean)
);
let kreditTurlar = Array.from(kreditTurlarSet);

// 3. Kredit summalarini topish (".00" bilan tugaydigan raqamlar)
let summalar = Array.from(document.querySelectorAll('td'))
    .filter(td => td.innerText.includes(",00") && !isNaN(parseFloat(td.innerText.replace(/\s/g, "").replace(",", "."))));

// 4. Xodimlar bo‘yicha ma'lumotlarni yig‘ish (faqat 11-ustunda "berilgan" bo‘lsa)
let xodimlar = {};

summalar.forEach(td => {
    let qator = td.closest('tr');
    if (!qator) return;

    // 11-ustundagi holatni tekshirish
    let holatTd = qator.querySelector('td:nth-child(11)');
    let holat = holatTd ? holatTd.innerText.trim().toLowerCase() : null;
    if (holat !== 'berilgan') return;

    let kreditTuri = qator.querySelector('td:nth-child(7)').innerText.trim();
    let xodim = qator.querySelector('td:nth-child(8)').innerText.trim();
    let summa = parseFloat(td.innerText.replace(/\s/g, "").replace(",", "."));

    if (!xodimlar[xodim]) {
        xodimlar[xodim] = {
            jamiSumma: 0,
            jamiHisob: 0,
            turlar: {}
        };
        kreditTurlar.forEach(tur => {
            xodimlar[xodim].turlar[tur] = {
                soni: 0,
                summa: 0
            };
        });
    }

    xodimlar[xodim].jamiSumma += summa;
    xodimlar[xodim].jamiHisob += 1;

    if (xodimlar[xodim].turlar[kreditTuri]) {
        xodimlar[xodim].turlar[kreditTuri].soni += 1;
        xodimlar[xodim].turlar[kreditTuri].summa += summa;
    }
});

// 5. Umumiy statistika
let umumiyJami = Object.values(xodimlar).reduce((a, b) => a + b.jamiSumma, 0);
let umumiyHisob = Object.values(xodimlar).reduce((a, b) => a + b.jamiHisob, 0);

// 6. Natijalarni chiqarish
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

// 7. Kredit turlari bo‘yicha umumiy statistikasi
let kreditTurlarStat = {};
kreditTurlar.forEach(tur => {
    kreditTurlarStat[tur] = { summa: 0, soni: 0 };
});

for (let xodim in xodimlar) {
    let info = xodimlar[xodim].turlar;
    for (let tur in info) {
        kreditTurlarStat[tur].summa += info[tur].summa;
        kreditTurlarStat[tur].soni += info[tur].soni;
    }
}

console.log(`\n📌 Kredit turlari bo‘yicha umumiy statistikasi:`);
for (let tur in kreditTurlarStat) {
    let { summa, soni } = kreditTurlarStat[tur];
    if (soni > 0) {
        console.log(`  - ${tur}: ${soni} ta, summa: ${summa.toLocaleString('fr-FR')} so'm`);
    }
}
