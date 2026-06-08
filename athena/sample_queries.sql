SELECT * FROM bus_arrival;
SELECT * FROM bus_arrival WHERE routeid = (SELECT routeid FROM bus_arrival LIMIT 1);
SELECT SUM(remainseatcnt) FROM bus_arrival;
SELECT COUNT(*) FROM bus_arrival WHERE remainseatcnt = 0;
SELECT routeid, AVG(remainseatcnt) AS AvgRemainSeats FROM bus_arrival GROUP BY routeid ORDER BY AvgRemainSeats DESC LIMIT 5;
